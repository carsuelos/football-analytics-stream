package tape

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/carsuelos/football-analytics-stream/markets/internal/schema"
)

var t0 = time.Date(2026, 10, 24, 17, 50, 0, 0, time.UTC)

func p(v float64) *float64 { return &v }

// board is a league with one game: Chelsea v Tottenham, Over 1.5 on Kalshi
// and Novig, at the given Kalshi ask.
func board(at time.Time, kalshiAsk float64, withNovig bool, clock string) schema.MarketBoard {
	quotes := []schema.Quote{{Venue: schema.VenueKalshi, MarketID: "K", Bid: p(kalshiAsk - 0.01), Ask: p(kalshiAsk), Fee: p(0.0175)}}
	if withNovig {
		quotes = append(quotes, schema.Quote{Venue: schema.VenueNovig, MarketID: "N", Bid: p(0.47), Ask: p(0.49), Fee: p(0)})
	}
	return schema.MarketBoard{
		SchemaVersion: 1, League: schema.LeagueEpl, UpdatedAt: at,
		Games: []schema.MarketGame{{
			ID: "epl-2026-10-24-chelsea-tottenham", League: schema.LeagueEpl,
			Home: schema.MarketTeam{Name: "Chelsea"}, Away: schema.MarketTeam{Name: "Tottenham"},
			Kickoff: t0.Add(-80 * time.Minute), State: schema.GameStateLive,
			Score: &schema.MarketScore{Home: 0, Away: 1}, Clock: &clock,
			Contracts: []schema.Contract{{Key: "total-over-1.5", Kind: schema.ContractKindTotal, Outcome: schema.OutcomeOver, Line: p(1.5), Label: "Over 1.5", Quotes: quotes}},
		}},
	}
}

func lines(t *testing.T, path string) []schema.MarketTapeRecord {
	t.Helper()
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	var out []schema.MarketTapeRecord
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		var r schema.MarketTapeRecord
		if err := json.Unmarshal(sc.Bytes(), &r); err != nil {
			t.Fatalf("%s: %v", sc.Text(), err)
		}
		out = append(out, r)
	}
	return out
}

func TestRecordWritesAKeyframeThenOnlyWhatChanged(t *testing.T) {
	dir := t.TempDir()
	r := New(dir)
	defer r.Close()
	for _, b := range []schema.MarketBoard{
		board(t0, 0.48, true, "63'"),
		board(t0.Add(10*time.Second), 0.48, true, "63'"),  // nothing changed: no line
		board(t0.Add(20*time.Second), 0.47, false, "64'"), // Kalshi moved, Novig gone
		board(t0.Add(11*time.Minute), 0.47, false, "74'"), // a keyframe again
	} {
		if err := r.Record(b); err != nil {
			t.Fatal(err)
		}
	}
	got := lines(t, filepath.Join(dir, "2026-10-24", "epl.jsonl"))
	if len(got) != 3 {
		t.Fatalf("%d lines: %+v", len(got), got)
	}
	k := got[0]
	if !k.Keyframe || *k.Home != "Chelsea" || len(k.Contracts) != 1 || *k.Contracts[0].Line != 1.5 || len(k.Quotes) != 2 || *k.Clock != "63'" {
		t.Errorf("keyframe %+v", k)
	}
	d := got[1]
	if d.Keyframe || d.Home != nil || d.Contracts != nil || len(d.Quotes) != 1 || *d.Quotes[0].Ask != 0.47 ||
		len(d.Gone) != 1 || d.Gone[0].Venue != schema.VenueNovig || *d.Clock != "64'" || *d.Score != (schema.MarketScore{Home: 0, Away: 1}) {
		t.Errorf("change %+v", d)
	}
	if !got[2].Keyframe || len(got[2].Quotes) != 1 {
		t.Errorf("second keyframe %+v", got[2])
	}
}

func TestRecordStartsANewFileEachDayWithKeyframes(t *testing.T) {
	dir := t.TempDir()
	r := New(dir)
	defer r.Close()
	late := time.Date(2026, 10, 24, 23, 59, 50, 0, time.UTC)
	for _, b := range []schema.MarketBoard{board(late, 0.48, true, "88'"), board(late.Add(20*time.Second), 0.48, true, "89'")} {
		if err := r.Record(b); err != nil {
			t.Fatal(err)
		}
	}
	if got := lines(t, filepath.Join(dir, "2026-10-25", "epl.jsonl")); len(got) != 1 || !got[0].Keyframe {
		t.Errorf("next day: %+v", got)
	}
	// A restart appends to the day's file, starting each game with a keyframe.
	r2 := New(dir)
	defer r2.Close()
	if err := r2.Record(board(late.Add(30*time.Second), 0.48, true, "89'")); err != nil {
		t.Fatal(err)
	}
	if got := lines(t, filepath.Join(dir, "2026-10-25", "epl.jsonl")); len(got) != 2 || !got[1].Keyframe {
		t.Errorf("after a restart: %+v", got)
	}
}
