package main

import (
	"bytes"
	"encoding/json"
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

func TestExportsATapeAsAFeed(t *testing.T) {
	// The feeds go inside the tapes' directory, as make livefeed-export puts them.
	tapes := t.TempDir()
	out := filepath.Join(tapes, "feeds")
	day := filepath.Join(tapes, "history", "2026-10-26")
	if err := os.MkdirAll(day, 0o755); err != nil {
		t.Fatal(err)
	}
	fixture := `{"id":42,"name":"Celtic vs Rangers","state_id":5,"starting_at":"2026-10-25 15:00:00","league_id":501,
		"league":{"name":"Premiership"},"season":{"name":"2026/2027"},
		"participants":[{"id":53,"name":"Celtic","meta":{"location":"home"}},{"id":62,"name":"Rangers","meta":{"location":"away"}}],
		"periods":[{"id":1,"type_id":1,"sort_order":1,"started":1000,"ended":3800},{"id":2,"type_id":2,"sort_order":2,"started":4700,"ended":7600}],
		"events":[{"id":9,"period_id":2,"participant_id":62,"type_id":14,"minute":70,"result":"0-1"}],
		"scores":[{"participant_id":53,"description":"CURRENT","score":{"goals":0}},{"participant_id":62,"description":"CURRENT","score":{"goals":1}}]}`
	var compact bytes.Buffer
	if err := json.Compact(&compact, []byte(fixture)); err != nil {
		t.Fatal(err)
	}
	tapeLine := `{"received_at":"2026-10-26T10:00:00Z","fixture_id":42,"keyframe":` + compact.String() + "}\n"
	if err := os.WriteFile(filepath.Join(day, "42.jsonl"), []byte(tapeLine), 0o644); err != nil {
		t.Fatal(err)
	}
	var log bytes.Buffer
	if err := run([]string{"-export", out, "-tapes", tapes}, env(nil), &log); err != nil {
		t.Fatal(err)
	}
	feed, err := os.ReadFile(filepath.Join(out, "42.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	var kinds []string
	for _, l := range strings.Split(strings.TrimSpace(string(feed)), "\n") {
		var m struct {
			Kind  string `json:"kind"`
			Event *struct {
				Type string `json:"type"`
			} `json:"event"`
		}
		if err := json.Unmarshal([]byte(l), &m); err != nil {
			t.Fatal(err)
		}
		if m.Event != nil {
			kinds = append(kinds, m.Event.Type)
		} else {
			kinds = append(kinds, m.Kind)
		}
	}
	want := "match_start half_start half_start half_end half_end half_start half_start shot half_end half_end match_end"
	if got := strings.Join(kinds, " "); got != want {
		t.Errorf("feed:\n got %s\nwant %s", got, want)
	}
	list, err := os.ReadFile(filepath.Join(out, "matches.json"))
	if err != nil || !strings.Contains(string(list), `"competition":"Premiership"`) || !strings.Contains(string(list), `"away_score":1`) {
		t.Errorf("matches.json %s, err %v", list, err)
	}
	if !strings.Contains(log.String(), "42 Celtic 0-1 Rangers: 9 events") {
		t.Errorf("log %q", log.String())
	}
	// Exporting again doesn't read the feeds as tapes.
	log.Reset()
	if err := run([]string{"-export", out, "-tapes", tapes}, env(nil), &log); err != nil {
		t.Fatal(err)
	}
	if strings.Count(log.String(), "events") != 1 || !strings.Contains(log.String(), "1 matches") {
		t.Errorf("second export: %q", log.String())
	}
}
