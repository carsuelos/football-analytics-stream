package board

import (
	"sync"
	"time"

	"github.com/carsuelos/football-analytics-stream/markets/internal/schema"
)

// History keeps, for each game seen, the best all-in price of each contract
// at each board, for keep, at most limit points a contract. A point the same
// as the last is only kept once a minute, so a quiet market stays small.
type History struct {
	keep  time.Duration
	limit int

	mu    sync.Mutex
	games map[string]*gameHistory
}

type gameHistory struct {
	seen   time.Time
	series map[string][]schema.PricePoint
	order  []string
}

func NewHistory(keep time.Duration, limit int) *History {
	return &History{keep: keep, limit: limit, games: map[string]*gameHistory{}}
}

// Record adds a board's prices.
func (h *History) Record(b schema.MarketBoard) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for _, g := range b.Games {
		gh := h.games[g.ID]
		if gh == nil {
			gh = &gameHistory{series: map[string][]schema.PricePoint{}}
			h.games[g.ID] = gh
		}
		gh.seen = b.UpdatedAt
		for _, c := range g.Contracts {
			if c.Best == nil || c.Implied == nil {
				continue
			}
			p := schema.PricePoint{T: b.UpdatedAt, AllIn: *c.Implied, Venue: *c.Best}
			pts, ok := gh.series[c.Key]
			if !ok {
				gh.order = append(gh.order, c.Key)
			}
			if n := len(pts); n > 0 {
				last := pts[n-1]
				if last.AllIn == p.AllIn && last.Venue == p.Venue && p.T.Sub(last.T) < time.Minute {
					continue
				}
			}
			pts = append(pts, p)
			for len(pts) > 0 && (len(pts) > h.limit || b.UpdatedAt.Sub(pts[0].T) > h.keep) {
				pts = pts[1:]
			}
			gh.series[c.Key] = pts
		}
	}
	for id, gh := range h.games {
		if b.UpdatedAt.Sub(gh.seen) > h.keep {
			delete(h.games, id)
		}
	}
}

// Get returns a game's history.
func (h *History) Get(id string) (schema.PriceHistory, bool) {
	h.mu.Lock()
	defer h.mu.Unlock()
	gh := h.games[id]
	if gh == nil {
		return schema.PriceHistory{}, false
	}
	out := schema.PriceHistory{SchemaVersion: 1, GameID: id, Series: []schema.PriceSeries{}}
	for _, k := range gh.order {
		pts := gh.series[k]
		out.Series = append(out.Series, schema.PriceSeries{Key: k, Points: append([]schema.PricePoint(nil), pts...)})
	}
	return out, true
}
