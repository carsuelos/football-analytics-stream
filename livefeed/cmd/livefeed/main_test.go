package main

import (
	"bytes"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/carsuelos/football-analytics-stream/livefeed/internal/sportmonks"
)

// fakeSportmonks serves a match that gains a statistic on every poll and a
// goal on the fifth, and the type catalogue. Like the free plan, it refuses
// the trends and ballCoordinates includes.
func fakeSportmonks(t *testing.T) (*httptest.Server, *atomic.Int32) {
	t.Helper()
	var polls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "tok" {
			w.WriteHeader(http.StatusUnauthorized)
			_, _ = w.Write([]byte(`{"message":"Unauthenticated."}`))
			return
		}
		switch r.URL.Path {
		case "/core/types":
			_, _ = w.Write([]byte(`{"data":[{"id":14,"name":"Goal"}],"pagination":{"has_more":false}}`))
		case "/football/livescores":
			for _, refused := range []string{"trends", "ballCoordinates"} {
				if strings.Contains(r.URL.Query().Get("include"), refused) {
					w.WriteHeader(http.StatusForbidden)
					fmt.Fprintf(w, `{"message":"You do not have access to the '%s' include"}`, strings.ToLower(refused))
					return
				}
			}
			n := int(polls.Add(1))
			var coords, events []string
			for i := range n {
				coords = append(coords, fmt.Sprintf(`{"id":%d,"type_id":34,"participant_id":1,"data":{"value":%d}}`, 100+i, i))
			}
			if n >= 5 {
				events = append(events, `{"id":9,"type_id":14,"minute":1}`)
			}
			fmt.Fprintf(w, `{"data":[{"id":42,"name":"Celtic vs Rangers","state_id":2,"events":[%s],"statistics":[%s]}],
				"rate_limit":{"resets_in_seconds":3600,"remaining":10000000,"requested_entity":"Fixture"}}`,
				strings.Join(events, ","), strings.Join(coords, ","))
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(srv.Close)
	return srv, &polls
}

func env(m map[string]string) func(string) string { return func(k string) string { return m[k] } }

func TestRecordsAMatchAndSummarizesIt(t *testing.T) {
	srv, polls := fakeSportmonks(t)
	dir := t.TempDir()
	args := []string{"-record", dir, "-base-url", srv.URL, "-interval", "20ms", "-idle-interval", "20ms", "-for", "400ms"}
	if err := run(args, env(map[string]string{"SPORTMONKS_API_TOKEN": "tok"}), &bytes.Buffer{}); err != nil {
		t.Fatal(err)
	}
	if polls.Load() < 6 {
		t.Fatalf("only %d polls", polls.Load())
	}
	if _, err := os.Stat(filepath.Join(dir, "types.json")); err != nil {
		t.Errorf("no type catalogue: %v", err)
	}
	var out bytes.Buffer
	if err := run([]string{"-summary", dir}, env(nil), &out); err != nil {
		t.Fatal(err)
	}
	s := out.String()
	t.Log("\n" + s)
	for _, want := range []string{"Celtic vs Rangers (fixture 42, state 2)", "events: Goal 1", "statistics "} {
		if !strings.Contains(s, want) {
			t.Errorf("summary lacks %q:\n%s", want, s)
		}
	}
	today := time.Now().UTC().Format(time.DateOnly)
	if _, err := os.Stat(filepath.Join(dir, today, "42.jsonl")); err != nil {
		t.Errorf("no tape: %v", err)
	}
}

func TestStopsOnABadTokenAndNeverPrintsIt(t *testing.T) {
	srv, _ := fakeSportmonks(t)
	err := run([]string{"-record", t.TempDir(), "-base-url", srv.URL}, env(map[string]string{"SPORTMONKS_API_TOKEN": "wrong-secret"}), &bytes.Buffer{})
	if err == nil || !strings.Contains(err.Error(), "401") || strings.Contains(err.Error(), "wrong-secret") {
		t.Errorf("err = %v", err)
	}
}

func TestNeedsAToken(t *testing.T) {
	err := run([]string{"-record", t.TempDir()}, env(nil), &bytes.Buffer{})
	if err == nil || !strings.Contains(err.Error(), "SPORTMONKS_API_TOKEN") {
		t.Errorf("err = %v", err)
	}
}

func TestPaceSpreadsTheHoursCallsOverTheHour(t *testing.T) {
	for _, c := range []struct {
		rl   *sportmonks.RateLimit
		want time.Duration
	}{
		{nil, 0},
		{&sportmonks.RateLimit{ResetsInSeconds: 3600, Remaining: 180}, 20 * time.Second}, // the free plan
		{&sportmonks.RateLimit{ResetsInSeconds: 3600, Remaining: 2000}, 1800 * time.Millisecond},
		{&sportmonks.RateLimit{ResetsInSeconds: 600, Remaining: 0}, 10 * time.Minute},
	} {
		if got := pace(c.rl); got != c.want {
			t.Errorf("pace(%+v) = %v, want %v", c.rl, got, c.want)
		}
	}
}
