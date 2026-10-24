// Package server is the markets service's HTTP API, under /api/markets so the
// dashboard's proxy can pass /api/markets/ straight through:
//
//	GET /api/markets/board?league=epl|laliga   the league's MarketBoard
//	GET /api/markets/games/{id}/history         a game's PriceHistory
//	GET /healthz                                 200 once serving
//
// Errors are {"error": "..."}, like the engine's.
package server

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/carsuelos/football-analytics-stream/markets/internal/schema"
)

// Markets is what the server serves: a board.Board.
type Markets interface {
	Get(ctx context.Context, league schema.League) (schema.MarketBoard, error)
	History(id string) (schema.PriceHistory, bool)
}

// New returns the API's handler.
func New(m Markets, log *slog.Logger) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.Write([]byte("ok\n"))
	})
	mux.HandleFunc("GET /api/markets/board", func(w http.ResponseWriter, r *http.Request) {
		league := schema.League(r.URL.Query().Get("league"))
		if league == "" {
			league = schema.LeagueEpl
		}
		b, err := m.Get(r.Context(), league)
		if err != nil {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}
		write(w, log, b)
	})
	mux.HandleFunc("GET /api/markets/games/{id}/history", func(w http.ResponseWriter, r *http.Request) {
		h, ok := m.History(r.PathValue("id"))
		if !ok {
			writeError(w, http.StatusNotFound, "no such game")
			return
		}
		write(w, log, h)
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, _ *http.Request) {
		writeError(w, http.StatusNotFound, "not found")
	})
	return mux
}

func write(w http.ResponseWriter, log *slog.Logger, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	if err := json.NewEncoder(w).Encode(v); err != nil && log != nil {
		log.Warn("writing a reply", "err", err)
	}
}

func writeError(w http.ResponseWriter, status int, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(map[string]string{"error": msg})
}
