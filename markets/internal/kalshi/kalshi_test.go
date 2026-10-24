package kalshi

import (
	"context"
	"fmt"
	"maps"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/carsuelos/football-analytics-stream/markets/internal/schema"
)

// fake serves the recorded series (testdata, trimmed from Kalshi's replies
// on Oct 24, 2026) and counts the requests.
func fake(t *testing.T) (*Client, *int) {
	t.Helper()
	n := new(int)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		*n++
		q := r.URL.Query()
		if r.URL.Path != "/events" || q.Get("status") != "open" || q.Get("with_nested_markets") != "true" {
			t.Errorf("unexpected request %s", r.URL)
		}
		body, err := os.ReadFile("testdata/" + q.Get("series_ticker") + ".json")
		if err != nil {
			http.NotFound(w, r)
			return
		}
		w.Write(body)
	}))
	t.Cleanup(srv.Close)
	return &Client{BaseURL: srv.URL, HTTP: srv.Client()}, n
}

func TestEventsJoinTheSeriesOfAGame(t *testing.T) {
	c, n := fake(t)
	events, err := c.Events(context.Background(), schema.LeagueEpl)
	if err != nil {
		t.Fatal(err)
	}
	if *n != 3 || len(events) != 2 {
		t.Fatalf("%d requests, %d events", *n, len(events))
	}
	e := events[0]
	if e.EventID != "26OCT24CFCTOT" || e.Home.Name != "Chelsea" || e.Away.Name != "Tottenham" ||
		e.Home.Abbreviation != "CFC" || e.Away.Abbreviation != "TOT" || !e.KickoffEstimated {
		t.Errorf("event = %+v", e)
	}
	// The result markets close 3h after kick-off (16:30 UTC).
	if want := time.Date(2026, 10, 24, 16, 30, 0, 0, time.UTC); !e.Kickoff.Equal(want) {
		t.Errorf("kickoff %v, want %v", e.Kickoff, want)
	}
	byKey := map[string]float64{}
	for _, q := range e.Quotes {
		if q.Ask == nil || q.FeeCoefficient != FeeCoefficient || !q.FeeCharged {
			t.Errorf("quote %+v", q)
			continue
		}
		key := string(q.Outcome)
		if q.Kind == schema.ContractKindTotal {
			key = "over-" + map[float64]string{0.5: "0.5", 1.5: "1.5", 2.5: "2.5", 3.5: "3.5"}[q.Line]
		}
		byKey[key] = *q.Ask
	}
	for key, ask := range map[string]float64{"over-0.5": 0.62, "over-1.5": 0.26, "home": 0.31, "away": 0.23, "draw": 0.48} {
		if byKey[key] != ask {
			t.Errorf("%s ask = %v, want %v (all: %v)", key, byKey[key], ask, byKey)
		}
	}
}

func TestEventsReadEachTeamsGoals(t *testing.T) {
	c, _ := fake(t)
	events, err := c.Events(context.Background(), schema.LeagueEpl)
	if err != nil {
		t.Fatal(err)
	}
	e := events[1] // Crystal Palace v Newcastle
	got := map[string]float64{}
	for _, q := range e.Quotes {
		if q.Kind == schema.ContractKindTeamTotal {
			got[fmt.Sprintf("%s-%g", q.Outcome, q.Line)] = *q.Ask
		}
	}
	want := map[string]float64{"home-0.5": 0.80, "home-1.5": 0.46, "home-2.5": 0.20, "away-0.5": 0.84, "away-1.5": 0.52, "away-2.5": 0.25}
	if !maps.Equal(got, want) {
		t.Errorf("team totals = %v, want %v", got, want)
	}
}

func TestEventsFailsOnAnErrorReply(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "slow down", http.StatusTooManyRequests)
	}))
	defer srv.Close()
	_, err := (&Client{BaseURL: srv.URL, HTTP: srv.Client()}).Events(context.Background(), schema.LeagueEpl)
	if err == nil || err.Error() != "kalshi: /events: 429 Too Many Requests slow down" {
		t.Errorf("err = %v", err)
	}
}

func TestDate(t *testing.T) {
	d, ok := date("26OCT24CFCTOT")
	if !ok || d.Format("2006-01-02") != "2026-10-24" {
		t.Errorf("date = %v, %v", d, ok)
	}
	if _, ok := date("bad"); ok {
		t.Error("parsed a bad key")
	}
}
