// Package broadcast publishes a loaded match as a live feed, in match time: an
// event at 10:00 is published ten minutes after kick-off at speed 1, or six
// seconds later at speed 100.
//
// Like a live provider, a Broadcaster publishes each match once, in order, and
// never goes back. Viewers that want to rewind or seek do it on their side, by
// reading the feed again from the start (the engine is such a viewer). Pause
// and speed are operator controls for demos: a match at speed 1 takes two hours.
//
// A Broadcaster has one goroutine (Run) that owns all broadcast state. Other
// goroutines never touch that state directly; they send requests over a
// channel and wait for a reply. Published events go into a feed, which any
// number of subscribers read independently.
package broadcast

import (
	"context"
	"errors"
	"fmt"
	"math"
	"time"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/match"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
)

var (
	// ErrNoMatch is returned by commands that need a loaded match.
	ErrNoMatch = errors.New("no match loaded")
	// ErrInvalidCommand is returned, wrapped, when a command is missing a
	// required field or has an out-of-range value.
	ErrInvalidCommand = errors.New("invalid command")
	// ErrStopped is returned once Run has returned.
	ErrStopped = errors.New("broadcaster stopped")
)

const (
	DefaultSpeed = 1.0
	MaxSpeed     = 1000.0

	// epsilon absorbs floating-point error when deciding whether an event is
	// due, so a timer that fires exactly on time never finds its event a
	// femtosecond in the future.
	epsilon = 1e-6
)

// Broadcaster broadcasts matches from a catalog.
type Broadcaster struct {
	catalog  match.Catalog
	feed     *feed
	requests chan request
	done     chan struct{}
}

// request is sent to the Run goroutine. A nil cmd asks only for the status.
type request struct {
	cmd   *schema.BroadcastCommand
	match *match.Match // already loaded, for load_match
	reply chan<- reply
}

type reply struct {
	status schema.BroadcastStatus
	err    error
}

func New(catalog match.Catalog) *Broadcaster {
	return &Broadcaster{
		catalog:  catalog,
		feed:     newFeed(),
		requests: make(chan request),
		done:     make(chan struct{}),
	}
}

// Run owns the broadcast state until ctx is cancelled. Call it exactly once,
// usually in its own goroutine.
func (b *Broadcaster) Run(ctx context.Context) {
	defer close(b.done)
	s := &state{feed: b.feed, speed: DefaultSpeed}
	for {
		// Sleep until the next event is due, unless a request arrives first.
		var due <-chan time.Time
		var timer *time.Timer
		if d, ok := s.untilNext(time.Now()); ok {
			timer = time.NewTimer(d)
			due = timer.C
		}
		// due stays nil when nothing is scheduled; receiving from a nil
		// channel blocks forever, so select simply ignores that case.
		select {
		case <-ctx.Done():
			return
		case req := <-b.requests:
			status, err := s.apply(req, time.Now())
			req.reply <- reply{status, err}
		case now := <-due:
			s.advance(now)
		}
		if timer != nil {
			timer.Stop()
		}
	}
}

// Execute applies a broadcast command and returns the resulting status.
func (b *Broadcaster) Execute(ctx context.Context, cmd schema.BroadcastCommand) (schema.BroadcastStatus, error) {
	req := request{cmd: &cmd}
	if cmd.Command == schema.BroadcastCommandCommandLoadMatch {
		if cmd.MatchID == nil {
			return schema.BroadcastStatus{}, fmt.Errorf("%w: load_match requires match_id", ErrInvalidCommand)
		}
		// Read from disk here, in the caller's goroutine, so the broadcast keeps
		// running while a large match loads.
		m, err := b.catalog.Load(int(*cmd.MatchID))
		if err != nil {
			return schema.BroadcastStatus{}, err
		}
		req.match = m
	}
	return b.do(ctx, req)
}

// Status returns the current broadcast status.
func (b *Broadcaster) Status(ctx context.Context) (schema.BroadcastStatus, error) {
	return b.do(ctx, request{})
}

// Subscribe returns a subscription to the feed starting at fromOffset.
func (b *Broadcaster) Subscribe(fromOffset int) *Subscription {
	return b.feed.subscribe(fromOffset)
}

func (b *Broadcaster) do(ctx context.Context, req request) (schema.BroadcastStatus, error) {
	// Buffered so that Run never blocks on replying.
	replies := make(chan reply, 1)
	req.reply = replies
	select {
	case b.requests <- req:
	case <-b.done:
		return schema.BroadcastStatus{}, ErrStopped
	case <-ctx.Done():
		return schema.BroadcastStatus{}, ctx.Err()
	}
	r := <-replies // Run replies to every request it accepts
	return r.status, r.err
}

// state is owned by the Run goroutine and never shared, so it needs no lock.
type state struct {
	feed    *feed
	match   *match.Match
	head    int      // next offset to publish
	pos     position // broadcast position at wall time anchor
	anchor  time.Time
	playing bool
	speed   float64
}

func (s *state) ended() bool {
	return s.match != nil && s.head == len(s.match.Events)
}

// now returns the broadcast position at wall time t.
func (s *state) now(t time.Time) position {
	if !s.playing {
		return s.pos
	}
	return position{s.pos.period, s.pos.clock + t.Sub(s.anchor).Seconds()*s.speed}
}

// untilNext returns how long to wait before the next event is due, and false
// if nothing is scheduled.
func (s *state) untilNext(t time.Time) (time.Duration, bool) {
	if !s.playing || s.match == nil || s.ended() {
		return 0, false
	}
	next, cur := eventPos(s.match.Events[s.head]), s.now(t)
	if next.period != cur.period || next.clock <= cur.clock {
		return 0, true
	}
	secs := (next.clock - cur.clock) / s.speed
	return time.Duration(math.Ceil(secs * float64(time.Second))), true
}

// advance publishes every event that is due at wall time t.
func (s *state) advance(t time.Time) {
	cur := s.now(t)
	start := s.head
	for !s.ended() {
		next := eventPos(s.match.Events[s.head])
		if next.period > cur.period {
			// Events arrive in feed order, so the current period is over:
			// skip the break and continue from the next period's first event.
			cur = next
		} else if next.period == cur.period && next.clock > cur.clock+epsilon {
			break
		}
		s.head++
	}
	s.pos, s.anchor = cur, t
	if s.head != start {
		s.feed.publish(s.head)
	}
	if s.ended() {
		s.playing = false
	}
}

func (s *state) apply(req request, t time.Time) (schema.BroadcastStatus, error) {
	if req.cmd == nil {
		return s.status(t), nil
	}
	cmd := req.cmd
	if cmd.Command != schema.BroadcastCommandCommandLoadMatch && s.match == nil {
		return s.status(t), ErrNoMatch
	}

	switch cmd.Command {
	case schema.BroadcastCommandCommandLoadMatch:
		s.match, s.head, s.pos, s.playing = req.match, 0, kickOff, false
		s.feed.load(req.match)

	case schema.BroadcastCommandCommandPlay:
		if !s.playing && !s.ended() {
			s.playing, s.anchor = true, t
		}

	case schema.BroadcastCommandCommandPause:
		s.pos, s.playing = s.now(t), false

	case schema.BroadcastCommandCommandSetSpeed:
		if cmd.Speed == nil || *cmd.Speed <= 0 || *cmd.Speed > MaxSpeed {
			return s.status(t), fmt.Errorf("%w: set_speed requires 0 < speed <= %v", ErrInvalidCommand, MaxSpeed)
		}
		// Re-anchor first so time already played is counted at the old speed.
		s.pos, s.anchor = s.now(t), t
		s.speed = *cmd.Speed

	default:
		return s.status(t), fmt.Errorf("%w: unknown command %q", ErrInvalidCommand, cmd.Command)
	}
	return s.status(t), nil
}

func (s *state) status(t time.Time) schema.BroadcastStatus {
	st := schema.BroadcastStatus{SchemaVersion: 1, State: schema.BroadcastStatusStateIdle, Speed: s.speed}
	if s.match == nil {
		return st
	}
	pos := s.now(t)
	id := s.match.MatchID
	offset := schema.Offset(s.head)
	period := schema.Period(pos.period)
	clock := schema.MatchClockSeconds(pos.clock)
	st.MatchID, st.Offset, st.Period, st.MatchClockS = &id, &offset, &period, &clock

	switch {
	case s.ended():
		st.State = schema.BroadcastStatusStateEnded
	case s.playing:
		st.State = schema.BroadcastStatusStatePlaying
	default:
		st.State = schema.BroadcastStatusStatePaused
	}
	return st
}
