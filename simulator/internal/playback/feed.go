package playback

import (
	"context"
	"sync"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/match"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
)

// position is a point in match time. The clock alone is ambiguous because
// periods overlap (first-half stoppage time runs past 45:00, the second half
// restarts at 45:00), so it is always paired with the period.
type position struct {
	period int
	clock  float64 // match_clock_s
}

func (p position) before(q position) bool {
	return p.period < q.period || (p.period == q.period && p.clock < q.clock)
}

func eventPos(ev schema.MatchEvent) position {
	return position{period: int(ev.Period), clock: float64(ev.MatchClockS)}
}

// kickOff is where every match starts.
var kickOff = position{period: 1, clock: 0}

// feed is the published part of the loaded match, Events[:head]. The playback
// goroutine is its only writer; any number of subscribers read it concurrently.
//
// It behaves like a broker log: each subscriber keeps its own cursor and reads
// at its own pace, so a slow client never holds up playback or other clients.
type feed struct {
	mu sync.Mutex
	// changed is closed and replaced on every write. Closing a channel wakes
	// every goroutine waiting on it, which makes it a cheap broadcast.
	changed chan struct{}

	match   *match.Match
	head    int // Events[:head] have been published
	loadGen int // incremented by every load
	seekGen int // incremented by every seek

	// Snapshot taken at the latest seek, sent to subscribers in the reset marker.
	seekHead int
	seekPos  position
}

func newFeed() *feed {
	return &feed{changed: make(chan struct{})}
}

// update applies fn under the lock and wakes all waiting subscribers.
func (f *feed) update(fn func()) {
	f.mu.Lock()
	defer f.mu.Unlock()
	fn()
	close(f.changed)
	f.changed = make(chan struct{})
}

func (f *feed) load(m *match.Match) {
	f.update(func() {
		f.match, f.head = m, 0
		f.loadGen++
	})
}

func (f *feed) publish(head int) {
	f.update(func() { f.head = head })
}

func (f *feed) seek(head int, pos position) {
	f.update(func() {
		f.head = head
		f.seekGen++
		f.seekHead, f.seekPos = head, pos
	})
}

// Subscription reads the feed from a given offset. It is not safe for
// concurrent use; give each client its own.
type Subscription struct {
	f       *feed
	cursor  int // next offset to send
	loadGen int // 0 until the first match_start has been sent
	seekGen int
	ended   bool // match_end already sent for the current match
	pending []schema.FeedMessage
}

func (f *feed) subscribe(fromOffset int) *Subscription {
	return &Subscription{f: f, cursor: max(fromOffset, 0)}
}

// Next blocks until the next message is available or ctx is done.
//
// A subscriber sees:
//   - match_start when it first syncs and whenever a new match is loaded;
//   - every published event, in offset order;
//   - reset after a seek, followed by a replay from offset 0, so consumers can
//     rebuild their state (see the reset marker for where the replay ends);
//   - match_end once the last event has been sent.
func (s *Subscription) Next(ctx context.Context) (schema.FeedMessage, error) {
	for {
		s.f.mu.Lock()
		msg, ok := s.next()
		changed := s.f.changed
		s.f.mu.Unlock()
		if ok {
			return msg, nil
		}
		select {
		case <-changed:
		case <-ctx.Done():
			return schema.FeedMessage{}, ctx.Err()
		}
	}
}

// next returns the next message if one is ready. It must be called with
// s.f.mu held.
func (s *Subscription) next() (schema.FeedMessage, bool) {
	if len(s.pending) > 0 {
		msg := s.pending[0]
		s.pending = s.pending[1:]
		return msg, true
	}
	f := s.f
	if f.match == nil {
		return schema.FeedMessage{}, false
	}
	events := f.match.Events

	switch {
	case s.loadGen != f.loadGen:
		if s.loadGen != 0 {
			s.cursor = 0 // a newly loaded match is always sent from the start
		}
		s.loadGen, s.seekGen, s.ended = f.loadGen, f.seekGen, false
		start := s.marker(schema.FeedMessageKindMatchStart, s.cursor, positionBefore(events, s.cursor))
		if s.cursor > f.head {
			// The client asked to resume past what has been published, e.g.
			// it missed a backward seek while disconnected. Its state is
			// ahead of the match, so make it rebuild.
			s.pending = append(s.pending, s.marker(schema.FeedMessageKindReset, f.head, positionBefore(events, f.head)))
			s.cursor = 0
		}
		return start, true

	case s.seekGen != f.seekGen:
		s.seekGen, s.ended, s.cursor = f.seekGen, false, 0
		return s.marker(schema.FeedMessageKindReset, f.seekHead, f.seekPos), true

	case s.cursor < f.head:
		ev := events[s.cursor] // a copy, so the receiver cannot modify the shared slice
		s.cursor++
		return schema.FeedMessage{SchemaVersion: 1, Kind: schema.FeedMessageKindEvent, Event: &ev}, true

	case s.cursor == len(events) && !s.ended:
		s.ended = true
		return s.marker(schema.FeedMessageKindMatchEnd, len(events), positionBefore(events, len(events))), true
	}
	return schema.FeedMessage{}, false
}

func (s *Subscription) marker(kind schema.FeedMessageKind, offset int, pos position) schema.FeedMessage {
	return schema.FeedMessage{
		SchemaVersion: 1,
		Kind:          kind,
		Marker: &schema.FeedMarker{
			MatchID:     s.f.match.MatchID,
			Offset:      schema.Offset(offset),
			Period:      schema.Period(pos.period),
			MatchClockS: schema.MatchClockSeconds(pos.clock),
		},
	}
}

// positionBefore is the match time just after Events[offset-1], i.e. where a
// stream starting at offset picks up.
func positionBefore(events []schema.MatchEvent, offset int) position {
	offset = min(offset, len(events))
	if offset == 0 {
		return kickOff
	}
	return eventPos(events[offset-1])
}
