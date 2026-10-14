package broadcast

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

func eventPos(ev schema.MatchEvent) position {
	return position{period: int(ev.Period), clock: float64(ev.MatchClockS)}
}

// kickOff is where every match starts.
var kickOff = position{period: 1, clock: 0}

// feed is the published part of the loaded match, Events[:head]. The broadcast
// goroutine is its only writer; any number of subscribers read it concurrently.
//
// It behaves like a broker log: each subscriber keeps its own cursor and reads
// at its own pace, from any offset up to the head, so a slow client never holds
// up the broadcast or other clients.
type feed struct {
	mu sync.Mutex
	// changed is closed and replaced on every write. Closing a channel wakes
	// every goroutine waiting on it, which makes it a cheap broadcast.
	changed chan struct{}

	match   *match.Match
	head    int // Events[:head] have been published
	loadGen int // incremented by every load
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

// Subscription reads the feed from a given offset. It is not safe for
// concurrent use; give each client its own.
type Subscription struct {
	f       *feed
	cursor  int  // next offset to send
	loadGen int  // 0 until the first match_start has been sent
	ended   bool // match_end already sent for the current match
}

func (f *feed) subscribe(fromOffset int) *Subscription {
	return &Subscription{f: f, cursor: max(fromOffset, 0)}
}

// Next blocks until the next message is available or ctx is done.
//
// A subscriber sees:
//   - match_start when it first syncs and whenever a new match is loaded,
//     with the head at that moment: offsets below it are a catch-up, not live;
//   - every published event, in offset order;
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
		s.loadGen, s.ended = f.loadGen, false
		if s.cursor > f.head {
			// The client asked to resume past what has been published, e.g.
			// the match was loaded again while it was away. Its state is
			// ahead of the broadcast, so send the match from the start.
			s.cursor = 0
		}
		start := s.marker(schema.FeedMessageKindMatchStart, s.cursor, positionBefore(events, s.cursor))
		head := schema.Offset(f.head)
		start.Marker.Head = &head
		return start, true

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

// Messages is the whole broadcast of m, as a subscriber there from the start
// receives it: a match_start with head 0, every event in feed order, then a
// match_end. An offline replay of these runs through the engine exactly as
// the live broadcast does (see cmd/export).
func Messages(m *match.Match) []schema.FeedMessage {
	f := newFeed()
	sub := f.subscribe(0)
	f.load(m)
	var msgs []schema.FeedMessage
	drain := func() {
		f.mu.Lock()
		defer f.mu.Unlock()
		for {
			msg, ok := sub.next()
			if !ok {
				return
			}
			msgs = append(msgs, msg)
		}
	}
	drain()
	f.publish(len(m.Events))
	drain()
	return msgs
}
