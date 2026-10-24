// Package tape records the boards' prices to disk, so trading strategies can
// be replayed later against what the venues really offered: a market tape.
//
// Each league's games go to <dir>/<UTC date>/<league>.jsonl, one
// MarketTapeRecord a line. A game's first line in a file, and one every
// KeyframeEvery after while it's live or about to start (IdleKeyframeEvery
// otherwise), is a keyframe with its whole state; the lines between
// have only what changed (quotes that moved, quotes no longer listed, and the
// game's state, score and clock). A game whose prices haven't changed since
// its last line gets no line. Reading a game back: from a keyframe, apply each
// line in order.
package tape

import (
	"bufio"
	"cmp"
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"sync"
	"time"

	"github.com/carsuelos/football-analytics-stream/markets/internal/schema"
)

// Recorder writes boards to a directory. Create it with New; it's safe to use
// from several goroutines.
type Recorder struct {
	Dir               string
	KeyframeEvery     time.Duration // games live or about to start
	IdleKeyframeEvery time.Duration // the others: days away, most of a tape otherwise

	mu    sync.Mutex
	files map[string]*file // by path
}

// file is one open tape and what it last said about each game.
type file struct {
	f     *os.File
	w     *bufio.Writer
	games map[string]*gameState
}

type gameState struct {
	keyframe time.Time
	quotes   map[quoteKey]schema.TapeQuote
	state    schema.GameState
	score    *schema.MarketScore
	clock    *string
}

type quoteKey struct {
	contract string
	venue    schema.Venue
}

// soon is how long before kick-off a game gets keyframes as often as a live one.
const soon = 15 * time.Minute

// New returns a recorder writing under dir, with a keyframe every 10 minutes
// for a game live or about to start, and every hour for the others.
func New(dir string) *Recorder {
	return &Recorder{Dir: dir, KeyframeEvery: 10 * time.Minute, IdleKeyframeEvery: time.Hour, files: map[string]*file{}}
}

// Record appends what changed on a league's board since the last call.
func (r *Recorder) Record(b schema.MarketBoard) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	t := b.UpdatedAt.UTC()
	path := filepath.Join(r.Dir, t.Format(time.DateOnly), string(b.League)+".jsonl")
	f, err := r.open(path)
	if err != nil {
		return err
	}
	for _, g := range b.Games {
		every := r.IdleKeyframeEvery
		if g.State == schema.GameStateLive || (g.State == schema.GameStateScheduled && g.Kickoff.Sub(t) < soon) {
			every = r.KeyframeEvery
		}
		rec, ok := f.next(g, b.League, t, every)
		if !ok {
			continue
		}
		line, err := json.Marshal(rec)
		if err != nil {
			return err
		}
		f.w.Write(line)
		f.w.WriteByte('\n')
	}
	return f.w.Flush()
}

// open returns the tape at path, opening it (and closing older days') if need be.
func (r *Recorder) open(path string) (*file, error) {
	if f := r.files[path]; f != nil {
		return f, nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, err
	}
	for p, f := range r.files {
		if filepath.Dir(p) != filepath.Dir(path) {
			f.f.Close()
			delete(r.files, p)
		}
	}
	osf, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return nil, err
	}
	f := &file{f: osf, w: bufio.NewWriter(osf), games: map[string]*gameState{}}
	r.files[path] = f
	return f, nil
}

// Close closes the open tapes.
func (r *Recorder) Close() error {
	r.mu.Lock()
	defer r.mu.Unlock()
	var first error
	for p, f := range r.files {
		if err := f.f.Close(); err != nil && first == nil {
			first = err
		}
		delete(r.files, p)
	}
	return first
}

// next is the game's line: a keyframe, what changed, or nothing.
func (f *file) next(g schema.MarketGame, l schema.League, t time.Time, every time.Duration) (schema.MarketTapeRecord, bool) {
	quotes := map[quoteKey]schema.TapeQuote{}
	var order []quoteKey
	for _, c := range g.Contracts {
		for _, q := range c.Quotes {
			k := quoteKey{c.Key, q.Venue}
			quotes[k] = schema.TapeQuote{Contract: c.Key, Venue: q.Venue, Bid: q.Bid, Ask: q.Ask, AskSize: q.AskSize, Fee: q.Fee}
			order = append(order, k)
		}
	}
	rec := schema.MarketTapeRecord{
		SchemaVersion: 1, T: t, League: l, GameID: g.ID,
		State: g.State, Score: g.Score, Clock: g.Clock, Quotes: []schema.TapeQuote{},
	}
	prev := f.games[g.ID]
	if prev == nil || t.Sub(prev.keyframe) >= every {
		rec.Keyframe = true
		home, away, kickoff := g.Home.Name, g.Away.Name, g.Kickoff
		rec.Home, rec.Away, rec.Kickoff = &home, &away, &kickoff
		for _, c := range g.Contracts {
			rec.Contracts = append(rec.Contracts, schema.TapeContract{Key: c.Key, Kind: c.Kind, Outcome: c.Outcome, Line: c.Line})
		}
		for _, k := range order {
			rec.Quotes = append(rec.Quotes, quotes[k])
		}
		f.games[g.ID] = &gameState{keyframe: t, quotes: quotes, state: g.State, score: g.Score, clock: g.Clock}
		return rec, true
	}
	for _, k := range order {
		if q, ok := prev.quotes[k]; !ok || !sameQuote(q, quotes[k]) {
			rec.Quotes = append(rec.Quotes, quotes[k])
		}
	}
	var gone []quoteKey
	for k := range prev.quotes {
		if _, ok := quotes[k]; !ok {
			gone = append(gone, k)
		}
	}
	slices.SortFunc(gone, func(a, b quoteKey) int {
		return cmp.Or(cmp.Compare(a.contract, b.contract), cmp.Compare(a.venue, b.venue))
	})
	for _, k := range gone {
		rec.Gone = append(rec.Gone, schema.TapeGone{Contract: k.contract, Venue: k.venue})
	}
	changed := len(rec.Quotes) > 0 || len(rec.Gone) > 0 || g.State != prev.state ||
		!equalPtr(g.Score, prev.score) || !equalPtr(g.Clock, prev.clock)
	if !changed {
		return rec, false
	}
	prev.quotes, prev.state, prev.score, prev.clock = quotes, g.State, g.Score, g.Clock
	return rec, true
}

func sameQuote(a, b schema.TapeQuote) bool {
	return equalPtr(a.Bid, b.Bid) && equalPtr(a.Ask, b.Ask) && equalPtr(a.AskSize, b.AskSize) && equalPtr(a.Fee, b.Fee)
}

func equalPtr[T comparable](a, b *T) bool {
	if a == nil || b == nil {
		return a == b
	}
	return *a == *b
}
