// Package playback replays a loaded match in match time: an event at 10:00 is
// published ten minutes after kick-off at speed 1, or six seconds later at
// speed 100. Playback can be paused, resumed, sped up and seeked.
//
// A Player has one goroutine (Run) that owns all playback state. Other
// goroutines never touch that state directly; they send requests over a
// channel and wait for a reply. Published events go into a feed, which any
// number of subscribers read independently.
package playback

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
	ErrStopped = errors.New("player stopped")
)

const (
	DefaultSpeed = 1.0
	MaxSpeed     = 1000.0

	// epsilon absorbs floating-point error when deciding whether an event is
	// due, so a timer that fires exactly on time never finds its event a
	// femtosecond in the future.
	epsilon = 1e-6
)

// Player replays matches from a catalog.
type Player struct {
	catalog  match.Catalog
	feed     *feed
	requests chan request
	done     chan struct{}
}

// request is sent to the Run goroutine. A nil cmd asks only for the status.
type request struct {
	cmd   *schema.PlaybackCommand
	match *match.Match // already loaded, for load_match
	reply chan<- reply
}

type reply struct {
	status schema.PlaybackStatus
	err    error
}

func New(catalog match.Catalog) *Player {
	return &Player{
		catalog:  catalog,
		feed:     newFeed(),
		requests: make(chan request),
		done:     make(chan struct{}),
	}
}

// Run owns the playback state until ctx is cancelled. Call it exactly once,
// usually in its own goroutine.
func (p *Player) Run(ctx context.Context) {
	defer close(p.done)
	s := &state{feed: p.feed, speed: DefaultSpeed}
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
		case req := <-p.requests:
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

// Execute applies a playback command and returns the resulting status.
func (p *Player) Execute(ctx context.Context, cmd schema.PlaybackCommand) (schema.PlaybackStatus, error) {
	req := request{cmd: &cmd}
	if cmd.Command == schema.PlaybackCommandCommandLoadMatch {
		if cmd.MatchID == nil {
			return schema.PlaybackStatus{}, fmt.Errorf("%w: load_match requires match_id", ErrInvalidCommand)
		}
		// Read from disk here, in the caller's goroutine, so playback keeps
		// running while a large match loads.
		m, err := p.catalog.Load(int(*cmd.MatchID))
		if err != nil {
			return schema.PlaybackStatus{}, err
		}
		req.match = m
	}
	return p.do(ctx, req)
}

// Status returns the current playback status.
func (p *Player) Status(ctx context.Context) (schema.PlaybackStatus, error) {
	return p.do(ctx, request{})
}

// Subscribe returns a subscription to the feed starting at fromOffset.
func (p *Player) Subscribe(fromOffset int) *Subscription {
	return p.feed.subscribe(fromOffset)
}

func (p *Player) do(ctx context.Context, req request) (schema.PlaybackStatus, error) {
	// Buffered so that Run never blocks on replying.
	replies := make(chan reply, 1)
	req.reply = replies
	select {
	case p.requests <- req:
	case <-p.done:
		return schema.PlaybackStatus{}, ErrStopped
	case <-ctx.Done():
		return schema.PlaybackStatus{}, ctx.Err()
	}
	r := <-replies // Run replies to every request it accepts
	return r.status, r.err
}

// state is owned by the Run goroutine and never shared, so it needs no lock.
type state struct {
	feed    *feed
	match   *match.Match
	head    int      // next offset to publish
	pos     position // playback position at wall time anchor
	anchor  time.Time
	playing bool
	speed   float64
}

func (s *state) ended() bool {
	return s.match != nil && s.head == len(s.match.Events)
}

// now returns the playback position at wall time t.
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

func (s *state) apply(req request, t time.Time) (schema.PlaybackStatus, error) {
	if req.cmd == nil {
		return s.status(t), nil
	}
	cmd := req.cmd
	if cmd.Command != schema.PlaybackCommandCommandLoadMatch && s.match == nil {
		return s.status(t), ErrNoMatch
	}

	switch cmd.Command {
	case schema.PlaybackCommandCommandLoadMatch:
		s.match, s.head, s.pos, s.playing = req.match, 0, kickOff, false
		s.feed.load(req.match)

	case schema.PlaybackCommandCommandPlay:
		if !s.playing && !s.ended() {
			s.playing, s.anchor = true, t
		}

	case schema.PlaybackCommandCommandPause:
		s.pos, s.playing = s.now(t), false

	case schema.PlaybackCommandCommandSetSpeed:
		if cmd.Speed == nil || *cmd.Speed <= 0 || *cmd.Speed > MaxSpeed {
			return s.status(t), fmt.Errorf("%w: set_speed requires 0 < speed <= %v", ErrInvalidCommand, MaxSpeed)
		}
		// Re-anchor first so time already played is counted at the old speed.
		s.pos, s.anchor = s.now(t), t
		s.speed = *cmd.Speed

	case schema.PlaybackCommandCommandSeek:
		target := cmd.SeekTo
		if target == nil || target.Period < 1 || target.Period > 5 || target.MatchClockS < 0 {
			return s.status(t), fmt.Errorf("%w: seek requires seek_to with period 1-5 and match_clock_s >= 0", ErrInvalidCommand)
		}
		s.seek(position{int(target.Period), float64(target.MatchClockS)}, t)

	default:
		return s.status(t), fmt.Errorf("%w: unknown command %q", ErrInvalidCommand, cmd.Command)
	}
	return s.status(t), nil
}

// seek moves playback to target. Events before target count as published;
// subscribers get a reset and replay them so they can rebuild their state.
// Playing or paused is preserved.
func (s *state) seek(target position, t time.Time) {
	events := s.match.Events
	head := 0
	for head < len(events) && eventPos(events[head]).before(target) {
		head++
	}
	// Seeking to (2, 0:00) would otherwise wait 45 minutes for the first
	// second-half event, so never start a period before its first event.
	if first, ok := periodStart(events, target.period); ok {
		target.clock = max(target.clock, first)
	}
	s.head, s.pos, s.anchor = head, target, t
	if s.ended() {
		s.playing = false
	}
	s.feed.seek(head, target)
}

// periodStart returns the clock of the first event in period.
func periodStart(events []schema.MatchEvent, period int) (float64, bool) {
	for _, ev := range events {
		if int(ev.Period) == period {
			return float64(ev.MatchClockS), true
		}
	}
	return 0, false
}

func (s *state) status(t time.Time) schema.PlaybackStatus {
	st := schema.PlaybackStatus{SchemaVersion: 1, State: schema.PlaybackStatusStateIdle, Speed: s.speed}
	if s.match == nil {
		return st
	}
	pos := s.now(t)
	id := schema.MatchID(s.match.ID)
	offset := schema.Offset(s.head)
	period := schema.Period(pos.period)
	clock := schema.MatchClockSeconds(pos.clock)
	st.MatchID, st.Offset, st.Period, st.MatchClockS = &id, &offset, &period, &clock

	switch {
	case s.ended():
		st.State = schema.PlaybackStatusStateEnded
	case s.playing:
		st.State = schema.PlaybackStatusStatePlaying
	default:
		st.State = schema.PlaybackStatusStatePaused
	}
	return st
}
