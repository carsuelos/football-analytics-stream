// Package server exposes the simulator over HTTP:
//
//	GET  /healthz                 liveness probe
//	GET  /matches                 MatchList of matches available to replay
//	GET  /status                  current PlaybackStatus
//	POST /control                 apply a PlaybackCommand, returns PlaybackStatus
//	GET  /feed?from_offset=N      WebSocket stream of FeedMessages, one per message
//
// Errors are returned as {"error": "..."} with a matching status code.
package server

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"strconv"
	"sync"
	"time"

	"github.com/coder/websocket"
	"github.com/coder/websocket/wsjson"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/match"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/playback"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
)

const (
	maxCommandBytes = 64 << 10
	// writeTimeout drops a feed client that stops reading, instead of letting
	// it hold a goroutine forever.
	writeTimeout = 10 * time.Second
)

type Server struct {
	player  *playback.Player
	catalog match.Catalog
	log     *slog.Logger
	feeds   sync.WaitGroup // open /feed connections
}

func New(player *playback.Player, catalog match.Catalog, log *slog.Logger) *Server {
	return &Server{player: player, catalog: catalog, log: log}
}

// WaitFeeds blocks until every /feed connection has closed, or ctx is done.
//
// http.Server.Shutdown does not wait for WebSocket connections, so call this
// after it. Feeds close themselves when their request context is cancelled
// (see http.Server.BaseContext).
func (s *Server) WaitFeeds(ctx context.Context) error {
	done := make(chan struct{})
	go func() {
		s.feeds.Wait()
		close(done)
	}()
	select {
	case <-done:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// Handler returns the HTTP routes. Method and path patterns such as
// "GET /status" are built into net/http since Go 1.22; a request with the
// wrong method gets 405 automatically.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.healthz)
	mux.HandleFunc("GET /matches", s.matches)
	mux.HandleFunc("GET /status", s.status)
	mux.HandleFunc("POST /control", s.control)
	mux.HandleFunc("GET /feed", s.feed)
	return mux
}

func (s *Server) healthz(w http.ResponseWriter, _ *http.Request) {
	w.Write([]byte("ok\n"))
}

func (s *Server) matches(w http.ResponseWriter, _ *http.Request) {
	infos, err := s.catalog.List()
	if err != nil {
		s.fail(w, err)
		return
	}
	if infos == nil {
		infos = []match.Info{} // encode as [] rather than null
	}
	writeJSON(w, http.StatusOK, schema.MatchList{SchemaVersion: 1, Matches: infos})
}

func (s *Server) status(w http.ResponseWriter, r *http.Request) {
	st, err := s.player.Status(r.Context())
	if err != nil {
		s.fail(w, err)
		return
	}
	writeJSON(w, http.StatusOK, st)
}

func (s *Server) control(w http.ResponseWriter, r *http.Request) {
	var cmd schema.PlaybackCommand
	// The generated UnmarshalJSON enforces the JSON Schema: required fields,
	// the command enum and the speed range.
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxCommandBytes)).Decode(&cmd); err != nil {
		writeError(w, http.StatusBadRequest, "invalid command: "+err.Error())
		return
	}
	st, err := s.player.Execute(r.Context(), cmd)
	if err != nil {
		s.fail(w, err)
		return
	}
	s.log.Info("playback command", "command", cmd.Command, "state", st.State)
	writeJSON(w, http.StatusOK, st)
}

func (s *Server) feed(w http.ResponseWriter, r *http.Request) {
	from := 0
	if v := r.URL.Query().Get("from_offset"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 0 {
			writeError(w, http.StatusBadRequest, "from_offset must be a non-negative integer")
			return
		}
		from = n
	}

	// With no options, browsers may only connect from the same origin. The
	// engine is not a browser and sends no Origin header, so it is allowed.
	conn, err := websocket.Accept(w, r, nil)
	if err != nil {
		return // Accept has already written an HTTP error response
	}
	s.feeds.Add(1)
	defer s.feeds.Done()
	defer conn.CloseNow()

	// Clients never send us data. CloseRead answers pings and returns a
	// context that is cancelled as soon as the client disconnects. It must not
	// inherit the request's cancellation: on shutdown it would drop the
	// connection without a close frame, before we can say StatusGoingAway.
	clientGone := conn.CloseRead(context.WithoutCancel(r.Context()))
	// ctx ends when the client leaves or the server shuts down.
	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()
	defer context.AfterFunc(clientGone, cancel)()
	s.log.Info("feed client connected", "remote", r.RemoteAddr, "from_offset", from)
	defer s.log.Info("feed client disconnected", "remote", r.RemoteAddr)

	sub := s.player.Subscribe(from)
	for {
		msg, err := sub.Next(ctx)
		if err != nil {
			// The client left or the server is shutting down.
			conn.Close(websocket.StatusGoingAway, "")
			return
		}
		if err := write(ctx, conn, msg); err != nil {
			return
		}
	}
}

func write(ctx context.Context, conn *websocket.Conn, msg schema.FeedMessage) error {
	ctx, cancel := context.WithTimeout(ctx, writeTimeout)
	defer cancel()
	return wsjson.Write(ctx, conn, msg)
}

// fail maps an error to an HTTP status. Unexpected errors are logged, and the
// client gets a generic message so internal details (such as file paths) stay
// private.
func (s *Server) fail(w http.ResponseWriter, err error) {
	code := http.StatusInternalServerError
	switch {
	case errors.Is(err, playback.ErrInvalidCommand):
		code = http.StatusBadRequest
	case errors.Is(err, match.ErrNotFound):
		code = http.StatusNotFound
	case errors.Is(err, playback.ErrNoMatch):
		code = http.StatusConflict
	case errors.Is(err, playback.ErrStopped):
		code = http.StatusServiceUnavailable
	}
	msg := err.Error()
	if code == http.StatusInternalServerError {
		s.log.Error("request failed", "err", err)
		msg = "internal error"
	}
	writeError(w, code, msg)
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]string{"error": msg})
}
