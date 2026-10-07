package server

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/coder/websocket"
	"github.com/coder/websocket/wsjson"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/match"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/playback"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
)

// These tests use a real HTTP server on localhost (httptest) and a real
// WebSocket client, so they exercise exactly what the engine will see.

func TestHealthz(t *testing.T) {
	srv := startServer(t)
	code, body := get(t, srv.URL+"/healthz")
	if code != http.StatusOK || body != "ok\n" {
		t.Errorf("got %d %q", code, body)
	}
}

func TestMatches(t *testing.T) {
	srv := startServer(t)
	code, body := get(t, srv.URL+"/matches")
	if code != http.StatusOK {
		t.Fatalf("status %d: %s", code, body)
	}
	var list schema.MatchList // the generated decoder checks the response against the schema
	if err := json.Unmarshal([]byte(body), &list); err != nil {
		t.Fatal(err)
	}
	if len(list.Matches) != 1 || list.Matches[0].MatchID != 1 || list.Matches[0].HomeTeam.Name != "Home FC" {
		t.Errorf("got %+v", list)
	}
}

func TestControlAndStatus(t *testing.T) {
	srv := startServer(t)

	var st schema.PlaybackStatus
	code, body := get(t, srv.URL+"/status")
	decode(t, code, body, &st)
	if st.State != schema.PlaybackStatusStateIdle {
		t.Errorf("initial state %s, want idle", st.State)
	}

	code, body = post(t, srv.URL+"/control", `{"schema_version": 1, "command": "load_match", "match_id": 1}`)
	decode(t, code, body, &st)
	if st.State != schema.PlaybackStatusStatePaused || st.MatchID == nil || *st.MatchID != 1 {
		t.Errorf("after load: %s", body)
	}

	code, body = post(t, srv.URL+"/control", `{"schema_version": 1, "command": "set_speed", "speed": 50}`)
	decode(t, code, body, &st)
	if st.Speed != 50 {
		t.Errorf("after set_speed: %s", body)
	}
}

func TestControlErrors(t *testing.T) {
	srv := startServer(t)
	tests := []struct {
		name string
		body string
		want int
	}{
		{"not json", `play`, http.StatusBadRequest},
		{"missing schema_version", `{"command": "play"}`, http.StatusBadRequest},
		{"unknown command", `{"schema_version": 1, "command": "rewind"}`, http.StatusBadRequest},
		{"play before load", `{"schema_version": 1, "command": "play"}`, http.StatusConflict},
		{"unknown match", `{"schema_version": 1, "command": "load_match", "match_id": 99}`, http.StatusNotFound},
		{"load without match_id", `{"schema_version": 1, "command": "load_match"}`, http.StatusBadRequest},
		{"speed out of range", `{"schema_version": 1, "command": "set_speed", "speed": 0}`, http.StatusBadRequest},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			code, body := post(t, srv.URL+"/control", tt.body)
			if code != tt.want {
				t.Errorf("status %d, want %d: %s", code, tt.want, body)
			}
			var e map[string]string
			if err := json.Unmarshal([]byte(body), &e); err != nil || e["error"] == "" {
				t.Errorf("want an error body, got %q", body)
			}
		})
	}

	resp, err := http.Get(srv.URL + "/control")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusMethodNotAllowed {
		t.Errorf("GET /control: %d, want 405", resp.StatusCode)
	}
}

func TestFeedStreamsLiveEvents(t *testing.T) {
	srv := startServer(t)
	conn := dial(t, srv, "")

	post(t, srv.URL+"/control", `{"schema_version": 1, "command": "load_match", "match_id": 1}`)
	post(t, srv.URL+"/control", `{"schema_version": 1, "command": "set_speed", "speed": 1000}`)
	post(t, srv.URL+"/control", `{"schema_version": 1, "command": "play"}`)

	expectFeed(t, conn, "match_start 0", "event 0", "event 1", "event 2", "match_end 3")
}

func TestFeedResumesFromOffset(t *testing.T) {
	srv := startServer(t)
	post(t, srv.URL+"/control", `{"schema_version": 1, "command": "load_match", "match_id": 1}`)
	post(t, srv.URL+"/control", `{"schema_version": 1, "command": "seek", "seek_to": {"period": 2, "match_clock_s": 3000}}`) // past the end

	conn := dial(t, srv, "?from_offset=2")
	expectFeed(t, conn, "match_start 2", "event 2", "match_end 3")
}

func TestFeedRejectsBadOffset(t *testing.T) {
	srv := startServer(t)
	for _, q := range []string{"-1", "abc"} {
		code, _ := get(t, srv.URL+"/feed?from_offset="+q)
		if code != http.StatusBadRequest {
			t.Errorf("from_offset=%s: %d, want 400", q, code)
		}
	}
}

func TestFeedRejectsCrossOriginBrowsers(t *testing.T) {
	srv := startServer(t)
	ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)
	defer cancel()
	_, resp, err := websocket.Dial(ctx, wsURL(srv, ""), &websocket.DialOptions{
		HTTPHeader: http.Header{"Origin": {"https://evil.example"}},
	})
	if err == nil || resp == nil || resp.StatusCode != http.StatusForbidden {
		t.Errorf("cross-origin dial: err=%v resp=%v, want 403", err, resp)
	}
}

func TestFeedSaysGoingAwayOnShutdown(t *testing.T) {
	srv, api, shutdown := startShutdownable(t)
	conn := dial(t, srv, "")
	post(t, srv.URL+"/control", `{"schema_version": 1, "command": "load_match", "match_id": 1}`)
	expectFeed(t, conn, "match_start 0")

	shutdown()
	ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)
	defer cancel()
	_, _, err := conn.Read(ctx)
	if got := websocket.CloseStatus(err); got != websocket.StatusGoingAway {
		t.Errorf("close status %v (err %v), want StatusGoingAway", got, err)
	}
	if err := api.WaitFeeds(ctx); err != nil {
		t.Errorf("feed handler did not return: %v", err)
	}
}

// --- helpers ---

type fakeCatalog map[int]*match.Match

func (c fakeCatalog) List() ([]match.Info, error) {
	var infos []match.Info
	for _, m := range c {
		infos = append(infos, m.Info)
	}
	return infos, nil
}

func (c fakeCatalog) Load(id int) (*match.Match, error) {
	if m, ok := c[id]; ok {
		return m, nil
	}
	return nil, fmt.Errorf("match %d: %w", id, match.ErrNotFound)
}

// startServer serves one match with events at (1, 0), (1, 10) and (2, 2700).
func startServer(t *testing.T) *httptest.Server {
	t.Helper()
	srv, _, _ := startShutdownable(t)
	return srv
}

// startShutdownable is startServer, plus the Server and a shutdown func that
// cancels every request context the way cmd/simulator does on Ctrl-C.
func startShutdownable(t *testing.T) (*httptest.Server, *Server, context.CancelFunc) {
	t.Helper()
	m := &match.Match{Info: match.Info{
		MatchID: 1, Competition: "Test Cup", Season: "2030", Stage: "Final", Date: "2030-07-14",
		HomeTeam: schema.Team{ID: 1, Name: "Home FC"}, AwayTeam: schema.Team{ID: 2, Name: "Away FC"},
	}}
	for i, p := range []struct {
		period int
		clock  float64
	}{{1, 0}, {1, 10}, {2, 2700}} {
		m.Events = append(m.Events, schema.MatchEvent{
			SchemaVersion: 1,
			ID:            fmt.Sprintf("e%d", i),
			MatchID:       1,
			Offset:        schema.Offset(i),
			Period:        schema.Period(p.period),
			MatchClockS:   schema.MatchClockSeconds(p.clock),
			Type:          schema.MatchEventTypeOther,
			Team:          m.HomeTeam,
		})
	}
	catalog := fakeCatalog{1: m}
	player := playback.New(catalog)
	go player.Run(t.Context())

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	api := New(player, catalog, logger)
	srv := httptest.NewUnstartedServer(api.Handler())
	ctx, shutdown := context.WithCancel(t.Context())
	srv.Config.BaseContext = func(net.Listener) context.Context { return ctx }
	srv.Start()
	t.Cleanup(srv.Close)
	return srv, api, shutdown
}

func wsURL(srv *httptest.Server, query string) string {
	return "ws" + strings.TrimPrefix(srv.URL, "http") + "/feed" + query
}

func dial(t *testing.T, srv *httptest.Server, query string) *websocket.Conn {
	t.Helper()
	ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)
	defer cancel()
	conn, _, err := websocket.Dial(ctx, wsURL(srv, query), nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { conn.CloseNow() })
	return conn
}

// expectFeed reads len(want) messages. Each is decoded into schema.FeedMessage,
// whose generated decoder validates it against the JSON Schema.
func expectFeed(t *testing.T, conn *websocket.Conn, want ...string) {
	t.Helper()
	ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)
	defer cancel()
	var got []string
	for range want {
		var msg schema.FeedMessage
		if err := wsjson.Read(ctx, conn, &msg); err != nil {
			t.Fatalf("after %q: %v", got, err)
		}
		if msg.Event != nil {
			got = append(got, fmt.Sprintf("event %d", msg.Event.Offset))
		} else {
			got = append(got, fmt.Sprintf("%s %d", msg.Kind, msg.Marker.Offset))
		}
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("feed:\n got %q\nwant %q", got, want)
	}
}

func get(t *testing.T, url string) (int, string) {
	t.Helper()
	resp, err := http.Get(url)
	if err != nil {
		t.Fatal(err)
	}
	return readResponse(t, resp)
}

func post(t *testing.T, url, body string) (int, string) {
	t.Helper()
	resp, err := http.Post(url, "application/json", strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	return readResponse(t, resp)
}

func readResponse(t *testing.T, resp *http.Response) (int, string) {
	t.Helper()
	defer resp.Body.Close()
	b, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	return resp.StatusCode, string(b)
}

func decode(t *testing.T, code int, body string, v any) {
	t.Helper()
	if code != http.StatusOK {
		t.Fatalf("status %d: %s", code, body)
	}
	if err := json.Unmarshal([]byte(body), v); err != nil {
		t.Fatalf("decode %s: %v", body, err)
	}
}
