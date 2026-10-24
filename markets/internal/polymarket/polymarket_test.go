package polymarket

import (
	"context"
	"encoding/json"
	"fmt"
	"maps"
	"net/http"
	"net/http/httptest"
	"os"
	"slices"
	"testing"
	"time"

	"github.com/carsuelos/football-analytics-stream/markets/internal/schema"
)

// fake serves the recorded listing (testdata/epl.json) and the markets
// (testdata/markets.json) a request's slugs name, as the gateway does.
func fake(t *testing.T) *Client {
	t.Helper()
	var markets marketsReply
	body, _ := os.ReadFile("testdata/markets.json")
	if err := json.Unmarshal(body, &markets); err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v2/leagues/epl/events":
			body, _ := os.ReadFile("testdata/epl.json")
			w.Write(body)
		case "/v1/markets":
			slugs := r.URL.Query()["slug"]
			if len(slugs) > slugsPerCall || r.URL.Query().Get("limit") == "" {
				t.Errorf("request for %d slugs, limit %q", len(slugs), r.URL.Query().Get("limit"))
			}
			var reply marketsReply
			for _, m := range markets.Markets {
				if slices.Contains(slugs, m.Slug) {
					reply.Markets = append(reply.Markets, m)
				}
			}
			json.NewEncoder(w).Encode(reply)
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(srv.Close)
	return &Client{BaseURL: srv.URL, HTTP: srv.Client()}
}

func TestEventsHaveTheResultMarketsAndTheLiveScore(t *testing.T) {
	events, err := fake(t).Events(context.Background(), schema.LeagueEpl)
	if err != nil {
		t.Fatal(err)
	}
	if len(events) != 2 {
		t.Fatalf("%d events", len(events))
	}
	live, later := events[0], events[1]
	if live.Home.Name != "Chelsea" || live.Away.Name != "Tottenham Hotspur" || live.Home.Abbreviation != "CFC" ||
		live.Home.Color != "#034694" || live.State != schema.GameStateLive || live.Clock != "65'" ||
		live.Score == nil || *live.Score != (schema.MarketScore{Home: 0, Away: 0}) ||
		!live.Kickoff.Equal(time.Date(2026, 10, 24, 16, 30, 0, 0, time.UTC)) || live.KickoffEstimated {
		t.Errorf("live event = %+v", live)
	}
	outcomes := map[schema.Outcome]float64{}
	for _, q := range live.Quotes {
		if q.Kind != schema.ContractKindResult {
			continue
		}
		if q.Ask == nil || q.FeeCoefficient != 0.0695 {
			t.Errorf("quote %+v", q)
			continue
		}
		outcomes[q.Outcome] = *q.Ask
	}
	if len(outcomes) != 3 {
		t.Errorf("outcomes %v, want home, draw and away", outcomes)
	}
	if later.State != schema.GameStateScheduled || later.Score != nil || later.Clock != "" {
		t.Errorf("later event = %+v", later)
	}
}

func TestEventsHaveTheTotalsBySlug(t *testing.T) {
	events, err := fake(t).Events(context.Background(), schema.LeagueEpl)
	if err != nil {
		t.Fatal(err)
	}
	e := events[1] // Crystal Palace v Newcastle
	got := map[string]float64{}
	for _, q := range e.Quotes {
		if q.Kind == schema.ContractKindResult {
			continue
		}
		if q.FeeCoefficient != 0.0695 || !q.FeeCharged || q.Bid == nil {
			t.Errorf("quote %+v", q)
		}
		got[fmt.Sprintf("%s-%s-%g", q.Kind, q.Outcome, q.Line)] = *q.Ask
	}
	want := map[string]float64{
		"total-over-0.5": 0.97, "total-over-1.5": 0.84, "total-over-2.5": 0.63, "total-over-3.5": 0.41, "total-over-4.5": 0.22, "total-over-5.5": 0.11,
		"team_total-home-0.5": 0.88, "team_total-home-1.5": 0.50, "team_total-home-2.5": 0.24,
		"team_total-away-0.5": 0.87, "team_total-away-1.5": 0.55, "team_total-away-2.5": 0.29,
	}
	if !maps.Equal(got, want) {
		t.Errorf("totals = %v\nwant %v", got, want)
	}
}

func TestScore(t *testing.T) {
	if s, ok := score("2-1"); !ok || s != (schema.MarketScore{Home: 2, Away: 1}) {
		t.Errorf("score = %v, %v", s, ok)
	}
	if _, ok := score(""); ok {
		t.Error("parsed an empty score")
	}
}
