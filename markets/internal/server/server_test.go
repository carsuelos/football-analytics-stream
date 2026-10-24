package server

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/carsuelos/football-analytics-stream/markets/internal/schema"
)

type fake struct{ asked []schema.League }

func (f *fake) Get(_ context.Context, l schema.League) (schema.MarketBoard, error) {
	f.asked = append(f.asked, l)
	if l != schema.LeagueEpl && l != schema.LeagueLaliga {
		return schema.MarketBoard{}, errors.New(`unknown league "seriea"`)
	}
	return schema.MarketBoard{SchemaVersion: 1, League: l, UpdatedAt: time.Unix(0, 0).UTC(), Venues: []schema.VenueStatus{}, Games: []schema.MarketGame{}}, nil
}

func (f *fake) History(id string) (schema.PriceHistory, bool) {
	if id != "g" {
		return schema.PriceHistory{}, false
	}
	return schema.PriceHistory{SchemaVersion: 1, GameID: "g", Series: []schema.PriceSeries{}}, true
}

func get(t *testing.T, h http.Handler, path string) (int, string) {
	t.Helper()
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
	body, _ := io.ReadAll(rec.Body)
	return rec.Code, string(body)
}

func TestRoutes(t *testing.T) {
	f := &fake{}
	h := New(f, nil)
	code, body := get(t, h, "/api/markets/board")
	var b schema.MarketBoard
	if code != 200 || json.Unmarshal([]byte(body), &b) != nil || b.League != schema.LeagueEpl {
		t.Errorf("board: %d %s", code, body)
	}
	if code, _ := get(t, h, "/api/markets/board?league=laliga"); code != 200 || f.asked[1] != schema.LeagueLaliga {
		t.Errorf("laliga: %d %v", code, f.asked)
	}
	for path, want := range map[string]struct {
		code int
		body string
	}{
		"/api/markets/board?league=seriea": {400, `{"error":"unknown league \"seriea\""}`},
		"/api/markets/games/g/history":     {200, `{"game_id":"g","schema_version":1,"series":[]}`},
		"/api/markets/games/x/history":     {404, `{"error":"no such game"}`},
		"/api/markets/nope":                {404, `{"error":"not found"}`},
		"/healthz":                         {200, "ok"},
	} {
		code, body := get(t, h, path)
		if code != want.code || body != want.body+"\n" {
			t.Errorf("%s: %d %q, want %d %q", path, code, body, want.code, want.body)
		}
	}
}
