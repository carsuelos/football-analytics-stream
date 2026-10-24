package polymarket

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/carsuelos/football-analytics-stream/markets/internal/schema"
)

func TestEventsHaveTheResultMarketsAndTheLiveScore(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v2/leagues/epl/events" {
			http.NotFound(w, r)
			return
		}
		body, _ := os.ReadFile("testdata/epl.json")
		w.Write(body)
	}))
	defer srv.Close()
	events, err := (&Client{BaseURL: srv.URL, HTTP: srv.Client()}).Events(context.Background(), schema.LeagueEpl)
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
		if q.Kind != schema.ContractKindResult || q.Ask == nil || q.FeeCoefficient != 0.0695 {
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

func TestScore(t *testing.T) {
	if s, ok := score("2-1"); !ok || s != (schema.MarketScore{Home: 2, Away: 1}) {
		t.Errorf("score = %v, %v", s, ok)
	}
	if _, ok := score(""); ok {
		t.Error("parsed an empty score")
	}
}
