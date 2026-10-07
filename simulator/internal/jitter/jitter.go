// Package jitter makes some events arrive late, so the engine's reorder buffer
// and watermark can be tested against a realistic feed.
//
// Each event gets a random delay between 0 and MaxDelay seconds of match time.
// Events are re-sorted by arrival time within their period and their offsets
// renumbered, so the offset is still the arrival order and resume works as
// usual, but match_clock_s is no longer monotonic. When an event arrives, no
// event already sent is more than MaxDelay ahead of it, so an engine watermark
// of at least MaxDelay accepts every event.
package jitter

import (
	"cmp"
	"math/rand/v2"
	"slices"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/match"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
)

// Catalog wraps another Catalog and jitters the matches it loads. The same
// seed and match always give the same order, so test runs are repeatable.
type Catalog struct {
	Inner    match.Catalog
	MaxDelay float64 // match seconds
	Seed     uint64
}

var _ match.Catalog = Catalog{}

func (c Catalog) List() ([]match.Info, error) { return c.Inner.List() }

func (c Catalog) Load(id int) (*match.Match, error) {
	m, err := c.Inner.Load(id)
	if err != nil {
		return nil, err
	}
	rng := rand.New(rand.NewPCG(c.Seed, uint64(id)))
	out := *m // copy, so a catalog that caches matches never sees them reordered
	out.Events = Apply(m.Events, c.MaxDelay, rng)
	return &out, nil
}

// Apply returns a copy of events, in feed order, with each event delayed by up
// to maxDelay match seconds.
func Apply(events []schema.MatchEvent, maxDelay float64, rng *rand.Rand) []schema.MatchEvent {
	type arrival struct {
		ev schema.MatchEvent
		at float64
	}
	arrivals := make([]arrival, len(events))
	for i, ev := range events {
		arrivals[i] = arrival{ev, float64(ev.MatchClockS) + rng.Float64()*maxDelay}
	}
	// Sorting by period first keeps every event inside its own period, so the
	// player still sees the periods in order. The sort is stable, so with no
	// delay the order is unchanged.
	slices.SortStableFunc(arrivals, func(a, b arrival) int {
		return cmp.Or(cmp.Compare(a.ev.Period, b.ev.Period), cmp.Compare(a.at, b.at))
	})
	out := make([]schema.MatchEvent, len(arrivals))
	for i, a := range arrivals {
		out[i] = a.ev
		out[i].Offset = schema.Offset(i)
	}
	return out
}
