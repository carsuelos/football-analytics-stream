package jitter

import (
	"fmt"
	"math/rand/v2"
	"slices"
	"testing"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/match"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
)

// events builds n events per period, one second apart. Each period starts
// 100s after the previous one, so with n > 100 their clocks overlap the way
// stoppage time makes real ones overlap.
func events(n int, periods ...int) []schema.MatchEvent {
	var evs []schema.MatchEvent
	for _, p := range periods {
		for i := range n {
			evs = append(evs, schema.MatchEvent{
				SchemaVersion: 1,
				ID:            fmt.Sprintf("p%d-%d", p, i),
				Offset:        schema.Offset(len(evs)),
				Period:        schema.Period(p),
				MatchClockS:   schema.MatchClockSeconds(float64((p-1)*100 + i)),
			})
		}
	}
	return evs
}

func ids(evs []schema.MatchEvent) []string {
	out := make([]string, len(evs))
	for i, ev := range evs {
		out[i] = ev.ID
	}
	return out
}

func TestNoDelayKeepsOrder(t *testing.T) {
	in := events(50, 1, 2)
	out := Apply(in, 0, rand.New(rand.NewPCG(1, 2)))
	if !slices.Equal(ids(in), ids(out)) {
		t.Errorf("order changed with no delay: %v", ids(out))
	}
}

func TestLatenessIsBounded(t *testing.T) {
	const maxDelay = 3.0
	in := events(500, 1, 2, 3)
	out := Apply(in, maxDelay, rand.New(rand.NewPCG(1, 2)))

	if got, want := slices.Sorted(slices.Values(ids(out))), slices.Sorted(slices.Values(ids(in))); !slices.Equal(got, want) {
		t.Fatal("events were added or lost")
	}
	late := 0
	ahead := 0.0 // latest clock already sent in the current period
	for i, ev := range out {
		if int(ev.Offset) != i {
			t.Fatalf("event %s has offset %d, want %d", ev.ID, ev.Offset, i)
		}
		clock := float64(ev.MatchClockS)
		if i == 0 || ev.Period != out[i-1].Period {
			if i > 0 && ev.Period < out[i-1].Period {
				t.Fatalf("period went backwards at offset %d", i)
			}
			ahead = clock
		}
		if lateness := ahead - clock; lateness > 0 {
			late++
			if lateness >= maxDelay {
				t.Errorf("event %s is %.2fs late, want < %v", ev.ID, lateness, maxDelay)
			}
		}
		ahead = max(ahead, clock)
	}
	if late == 0 {
		t.Error("no event arrived late; jitter did nothing")
	}
	t.Logf("%d of %d events arrived late", late, len(out))
}

// stubCatalog returns the same *Match on every load, like a cache would.
type stubCatalog struct{ m *match.Match }

func (c stubCatalog) List() ([]match.Info, error)    { return []match.Info{c.m.Info}, nil }
func (c stubCatalog) Load(int) (*match.Match, error) { return c.m, nil }

func TestCatalogIsRepeatableAndLeavesInnerAlone(t *testing.T) {
	orig := &match.Match{Info: match.Info{MatchID: 7}, Events: events(200, 1)}
	before := ids(orig.Events)
	c := Catalog{Inner: stubCatalog{orig}, MaxDelay: 5, Seed: 42}

	a, err := c.Load(7)
	if err != nil {
		t.Fatal(err)
	}
	b, _ := c.Load(7)
	if !slices.Equal(ids(a.Events), ids(b.Events)) {
		t.Error("same seed gave different orders")
	}
	if slices.Equal(ids(a.Events), before) {
		t.Error("events were not reordered")
	}
	if !slices.Equal(ids(orig.Events), before) || orig.Events[0].Offset != 0 {
		t.Error("inner catalog's match was modified")
	}

	other, _ := Catalog{Inner: stubCatalog{orig}, MaxDelay: 5, Seed: 43}.Load(7)
	if slices.Equal(ids(a.Events), ids(other.Events)) {
		t.Error("different seeds gave the same order")
	}
}
