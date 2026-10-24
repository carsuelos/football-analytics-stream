package novig

import (
	"context"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/carsuelos/football-analytics-stream/markets/internal/schema"
)

func fake(t *testing.T) *Client {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		if q.Get("league") != "EPL" || r.Header.Get("Novig-Key-Id") != "" {
			t.Errorf("unexpected request %s", r.URL)
		}
		var file string
		switch r.URL.Path {
		case "/v3/public/catalog/events":
			file = "testdata/events.json"
		case "/v3/public/catalog/markets":
			if q.Get("marketType") != marketTypes {
				t.Errorf("market types %q", q.Get("marketType"))
			}
			file = "testdata/markets.json"
		default:
			http.NotFound(w, r)
			return
		}
		body, _ := os.ReadFile(file)
		w.Write(body)
	}))
	t.Cleanup(srv.Close)
	return &Client{BaseURL: srv.URL, HTTP: srv.Client()}
}

func near(a *float64, b float64) bool { return a != nil && math.Abs(*a-b) < 1e-9 }

func TestEventsReadTheAskFromTheOtherSidesBid(t *testing.T) {
	events, err := fake(t).Events(context.Background(), schema.LeagueEpl)
	if err != nil {
		t.Fatal(err)
	}
	var live *struct{}
	for _, e := range events {
		if e.Home.Name != "Chelsea FC" {
			continue
		}
		live = &struct{}{}
		if e.Away.Name != "Tottenham Hotspur FC" || e.State != schema.GameStateLive ||
			!e.Kickoff.Equal(time.Date(2026, 10, 24, 16, 30, 0, 0, time.UTC)) {
			t.Errorf("event = %+v", e)
		}
		got := map[string]bool{}
		for _, q := range e.Quotes {
			if !q.FeeCharged || q.FeeCoefficient != 0.06 {
				t.Errorf("a live game's fee: %+v", q)
			}
			switch {
			case q.Kind == schema.ContractKindTotal && q.Line == 0.5:
				// Over 0.5 bid 0.635; Under 0.5 bid 0.36 for 18002 1¢ contracts.
				if !near(q.Bid, 0.635) || !near(q.Ask, 0.64) || !near(q.AskSize, 180.02) {
					t.Errorf("over 0.5: bid %v ask %v size %v", *q.Bid, *q.Ask, *q.AskSize)
				}
				got["over-0.5"] = true
			case q.Outcome == schema.OutcomeHome:
				if !near(q.Bid, 0.305) || !near(q.Ask, 0.31) {
					t.Errorf("home: %+v", q)
				}
				got["home"] = true
			case q.Outcome == schema.OutcomeAway:
				got["away"] = true
			case q.Outcome == schema.OutcomeDraw:
				if !near(q.Ask, 0.465) {
					t.Errorf("draw ask %v", *q.Ask)
				}
				got["draw"] = true
			}
		}
		if len(got) != 4 {
			t.Errorf("got %v", got)
		}
	}
	if live == nil {
		t.Fatalf("no Chelsea game in %+v", events)
	}
}

func TestStrikeAsNumberOrString(t *testing.T) {
	var f flexFloat
	for _, in := range []string{`2.5`, `"2.5"`} {
		if err := f.UnmarshalJSON([]byte(in)); err != nil || f != 2.5 {
			t.Errorf("%s: %v, %v", in, f, err)
		}
	}
}
