package broadcast

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"os"
	"reflect"
	"testing"
	"testing/synctest"
	"time"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/match"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/statsbomb"
)

// Every test runs inside synctest.Test, which gives the bubble a fake clock:
// time only moves when all goroutines are blocked, and it jumps straight to the
// next timer. A two-hour match replays instantly, and arrival times are exact.

func TestPlaysInMatchTime(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		h := start(t, newMatch(1, at(1, 0), at(1, 10), at(1, 30)))
		h.do(load(1))
		sub := h.b.Subscribe(0)
		h.do(setSpeed(2))
		h.do(play())

		h.expect(sub,
			"match_start m1 0 (1, 0) head 1 @0s",
			"event m1-e0 @0s",
			"event m1-e1 @5s", // 10 s of match time at speed 2
			"event m1-e2 @15s",
			"match_end m1 3 (1, 30) @15s",
		)
		h.expectStatus(schema.BroadcastStatusStateEnded, 3, 1, 30)
	})
}

func TestSkipsBreakBetweenPeriods(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		// The first half runs to 46:00 with stoppage time; the second half
		// restarts at 45:00, so the clock goes backwards between periods.
		h := start(t, newMatch(1, at(1, 0), at(1, 2760), at(2, 2700), at(2, 2710)))
		h.do(load(1))
		sub := h.b.Subscribe(0)
		h.do(play())

		h.expect(sub,
			"match_start m1 0 (1, 0) head 1 @0s",
			"event m1-e0 @0s",
			"event m1-e1 @2760s",
			"event m1-e2 @2760s", // half time is skipped
			"event m1-e3 @2770s",
			"match_end m1 4 (2, 2710) @2770s",
		)
	})
}

func TestPauseAndResume(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		h := start(t, newMatch(1, at(1, 0), at(1, 10), at(1, 20)))
		h.do(load(1))
		sub := h.b.Subscribe(0)
		h.do(play())
		h.expect(sub, "match_start m1 0 (1, 0) head 1 @0s", "event m1-e0 @0s", "event m1-e1 @10s")

		time.Sleep(5 * time.Second)
		h.do(pause())
		h.expectStatus(schema.BroadcastStatusStatePaused, 2, 1, 15)

		time.Sleep(100 * time.Second) // the match clock stands still
		h.expectStatus(schema.BroadcastStatusStatePaused, 2, 1, 15)
		h.do(play())
		h.expect(sub, "event m1-e2 @120s", "match_end m1 3 (1, 20) @120s")
	})
}

func TestSetSpeedWhilePlaying(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		h := start(t, newMatch(1, at(1, 0), at(1, 100)))
		h.do(load(1))
		sub := h.b.Subscribe(0)
		h.do(play())
		h.expect(sub, "match_start m1 0 (1, 0) head 1 @0s", "event m1-e0 @0s")

		time.Sleep(50 * time.Second)
		h.do(setSpeed(10)) // 50 s of match time left, at 10x
		h.expect(sub, "event m1-e1 @55s", "match_end m1 2 (1, 100) @55s")
	})
}

func TestStatusInterpolatesClock(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		h := start(t, newMatch(1, at(1, 0), at(1, 100)))
		h.expectIdle()
		h.do(load(1))
		h.expectStatus(schema.BroadcastStatusStatePaused, 0, 1, 0)
		h.do(play())
		time.Sleep(3500 * time.Millisecond)
		h.expectStatus(schema.BroadcastStatusStatePlaying, 1, 1, 3.5)
	})
}

func TestLateSubscriberCatchesUp(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		h := start(t, newMatch(1, at(1, 0), at(1, 10), at(1, 20), at(1, 30)))
		h.do(load(1))
		h.do(play())
		time.Sleep(15 * time.Second)

		// What was published before it subscribed arrives at once, then the
		// rest as it is broadcast. The head says where the catch-up ends.
		h.expect(h.b.Subscribe(0),
			"match_start m1 0 (1, 0) head 2 @15s",
			"event m1-e0 @15s",
			"event m1-e1 @15s",
			"event m1-e2 @20s",
			"event m1-e3 @30s",
			"match_end m1 4 (1, 30) @30s",
		)
	})
}

func TestSubscribeFromOffset(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		h := start(t, newMatch(1, at(1, 0), at(1, 10), at(1, 20)))
		h.do(load(1))
		h.do(play())
		time.Sleep(time.Minute) // publish everything

		h.expect(h.b.Subscribe(1),
			"match_start m1 1 (1, 0) head 3 @60s", "event m1-e1 @60s", "event m1-e2 @60s", "match_end m1 3 (1, 20) @60s")
	})
}

func TestSubscribePastHeadStartsFromKickOff(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		h := start(t, newMatch(1, at(1, 0), at(1, 10), at(1, 20)))
		h.do(load(1))
		h.do(play())

		// A client that saw offsets 0-2 of an earlier broadcast reconnects after
		// the match was loaded again: it is ahead, so it gets the match from the start.
		sub := h.b.Subscribe(3)
		h.expect(sub, "match_start m1 0 (1, 0) head 1 @0s", "event m1-e0 @0s", "event m1-e1 @10s")
	})
}

func TestLoadingAnotherMatchRestartsSubscribers(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		h := start(t, newMatch(1, at(1, 0), at(1, 10)), newMatch(2, at(1, 0)))
		h.do(load(1))
		sub := h.b.Subscribe(0)
		h.do(play())
		h.expect(sub, "match_start m1 0 (1, 0) head 1 @0s", "event m1-e0 @0s")

		h.do(load(2)) // a new match starts paused
		h.expectStatus(schema.BroadcastStatusStatePaused, 0, 1, 0)
		h.do(play())
		h.expect(sub, "match_start m2 0 (1, 0) head 1 @0s", "event m2-e0 @0s", "match_end m2 1 (1, 0) @0s")
	})
}

func TestSlowSubscriberDoesNotBlockTheBroadcast(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		h := start(t, newMatch(1, at(1, 0), at(1, 10), at(1, 20)))
		h.do(load(1))
		_ = h.b.Subscribe(0) // never read
		h.do(play())
		time.Sleep(time.Minute)
		h.expectStatus(schema.BroadcastStatusStateEnded, 3, 1, 20)
	})
}

func TestCommandErrors(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		h := start(t, newMatch(1, at(1, 0)))
		tooFast := MaxSpeed + 1
		missingID := load(1)
		missingID.MatchID = nil

		tests := []struct {
			name string
			cmd  schema.BroadcastCommand
			want error
		}{
			{"play before load", play(), ErrNoMatch},
			{"unknown match", load(99), match.ErrNotFound},
			{"load without id", missingID, ErrInvalidCommand},
			{"load", load(1), nil},
			{"set_speed without speed", schema.BroadcastCommand{Command: schema.BroadcastCommandCommandSetSpeed}, ErrInvalidCommand},
			{"zero speed", setSpeed(0), ErrInvalidCommand},
			{"speed too high", schema.BroadcastCommand{Command: schema.BroadcastCommandCommandSetSpeed, Speed: &tooFast}, ErrInvalidCommand},
			{"unknown command", schema.BroadcastCommand{Command: "rewind"}, ErrInvalidCommand},
		}
		for _, tt := range tests {
			_, err := h.b.Execute(t.Context(), tt.cmd)
			if !errors.Is(err, tt.want) {
				t.Errorf("%s: error = %v, want %v", tt.name, err, tt.want)
			}
		}
	})
}

func TestStoppedBroadcaster(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		b := New(stubCatalog{})
		ctx, cancel := context.WithCancel(t.Context())
		go b.Run(ctx)
		cancel()
		synctest.Wait() // until Run has returned
		if _, err := b.Status(t.Context()); !errors.Is(err, ErrStopped) {
			t.Errorf("Status after stop: %v, want ErrStopped", err)
		}
	})
}

// TestBroadcastsWorldCupFinal plays the whole 2022 final at real speed. Under
// synctest it takes a fraction of a second. Skipped unless the data is fetched.
func TestBroadcastsWorldCupFinal(t *testing.T) {
	const dataDir = "../../../data/statsbomb"
	if _, err := os.Stat(dataDir + "/events/3869685.json"); err != nil {
		t.Skip("World Cup final not downloaded; run: make fetch-data")
	}
	synctest.Test(t, func(t *testing.T) {
		b := New(statsbomb.NewCatalog(dataDir))
		go b.Run(t.Context())
		h := &harness{t: t, b: b, start: time.Now()}
		h.do(load(3869685))
		sub := b.Subscribe(0)
		h.do(play())

		var events []schema.MatchEvent
		for {
			msg, err := sub.Next(t.Context())
			if err != nil {
				t.Fatal(err)
			}
			if msg.Kind == schema.FeedMessageKindMatchEnd {
				break
			}
			if msg.Event != nil {
				events = append(events, *msg.Event)
			}
		}
		if len(events) != 4407 {
			t.Fatalf("got %d events, want 4407", len(events))
		}
		for i, ev := range events {
			if int(ev.Offset) != i {
				t.Fatalf("event %d has offset %d", i, ev.Offset)
			}
		}

		// Expected wall time: the clock time played in each period, with the
		// breaks between periods skipped.
		cur, want := kickOff, 0.0
		for _, ev := range events {
			p := eventPos(ev)
			switch {
			case p.period > cur.period:
				cur = p
			case p.period == cur.period && p.clock > cur.clock:
				want += p.clock - cur.clock
				cur = p
			}
		}
		got := time.Since(h.start).Seconds()
		if math.Abs(got-want) > 1e-3 {
			t.Errorf("broadcast took %.3fs, want %.3fs", got, want)
		}
		t.Logf("broadcast %d events in %v of match time", len(events), time.Since(h.start).Round(time.Second))
	})
}

// --- helpers ---

type stubCatalog map[int]*match.Match

func (c stubCatalog) List() ([]match.Info, error) {
	var infos []match.Info
	for _, m := range c {
		infos = append(infos, m.Info)
	}
	return infos, nil
}

func (c stubCatalog) Load(id int) (*match.Match, error) {
	m, ok := c[id]
	if !ok {
		return nil, fmt.Errorf("match %d: %w", id, match.ErrNotFound)
	}
	return m, nil
}

func at(period int, clock float64) position { return position{period, clock} }

// newMatch builds a match whose event ids read "m<match>-e<offset>".
func newMatch(id int, positions ...position) *match.Match {
	m := &match.Match{Info: match.Info{MatchID: schema.MatchID(id)}}
	for i, p := range positions {
		m.Events = append(m.Events, schema.MatchEvent{
			SchemaVersion: 1,
			ID:            fmt.Sprintf("m%d-e%d", id, i),
			MatchID:       schema.MatchID(id),
			Offset:        schema.Offset(i),
			Period:        schema.Period(p.period),
			MatchClockS:   schema.MatchClockSeconds(p.clock),
			Type:          schema.MatchEventTypeOther,
			Team:          schema.Team{ID: 1, Name: "Home FC"},
		})
	}
	return m
}

func command(c schema.BroadcastCommandCommand) schema.BroadcastCommand {
	return schema.BroadcastCommand{SchemaVersion: 1, Command: c}
}

func load(id int) schema.BroadcastCommand {
	cmd, mid := command(schema.BroadcastCommandCommandLoadMatch), schema.MatchID(id)
	cmd.MatchID = &mid
	return cmd
}

func play() schema.BroadcastCommand  { return command(schema.BroadcastCommandCommandPlay) }
func pause() schema.BroadcastCommand { return command(schema.BroadcastCommandCommandPause) }

func setSpeed(speed float64) schema.BroadcastCommand {
	cmd := command(schema.BroadcastCommandCommandSetSpeed)
	cmd.Speed = &speed
	return cmd
}

type harness struct {
	t     *testing.T
	b     *Broadcaster
	start time.Time // fake wall time at the start of the test
}

// start runs a broadcaster over the given matches. Run stops when the test's
// context is cancelled at the end of the test.
func start(t *testing.T, matches ...*match.Match) *harness {
	catalog := stubCatalog{}
	for _, m := range matches {
		catalog[int(m.MatchID)] = m
	}
	b := New(catalog)
	go b.Run(t.Context())
	return &harness{t: t, b: b, start: time.Now()}
}

// do executes cmd, then waits until the broadcaster has acted on it: Run replies
// before it publishes the events that are due, so without the wait a
// subscriber could read the feed before they are published.
func (h *harness) do(cmd schema.BroadcastCommand) schema.BroadcastStatus {
	h.t.Helper()
	st, err := h.b.Execute(h.t.Context(), cmd)
	if err != nil {
		h.t.Fatalf("%s: %v", cmd.Command, err)
	}
	synctest.Wait()
	roundTrip(h.t, &st)
	return st
}

// expect reads len(want) messages and compares them, with their arrival
// times, against want.
func (h *harness) expect(sub *Subscription, want ...string) {
	h.t.Helper()
	got := make([]string, 0, len(want))
	for range want {
		msg, err := sub.Next(h.t.Context())
		if err != nil {
			h.t.Fatal(err)
		}
		roundTrip(h.t, &msg)
		got = append(got, fmt.Sprintf("%s @%gs", describe(msg), time.Since(h.start).Seconds()))
	}
	if !reflect.DeepEqual(got, want) {
		h.t.Errorf("feed messages:\n got %q\nwant %q", got, want)
	}
}

// expectNothing checks that no message arrives within an hour of fake time.
func (h *harness) expectNothing(sub *Subscription) {
	h.t.Helper()
	ctx, cancel := context.WithTimeout(h.t.Context(), time.Hour)
	defer cancel()
	if msg, err := sub.Next(ctx); err == nil {
		h.t.Errorf("unexpected message: %s", describe(msg))
	}
}

func (h *harness) expectStatus(state schema.BroadcastStatusState, offset, period int, clock float64) {
	h.t.Helper()
	st, err := h.b.Status(h.t.Context())
	if err != nil {
		h.t.Fatal(err)
	}
	roundTrip(h.t, &st)
	if st.State != state || st.Offset == nil || int(*st.Offset) != offset ||
		st.Period == nil || int(*st.Period) != period || st.MatchClockS == nil || float64(*st.MatchClockS) != clock {
		h.t.Errorf("status = %s offset=%v period=%v clock=%v; want %s offset=%d period=%d clock=%v",
			st.State, deref(st.Offset), deref(st.Period), deref(st.MatchClockS), state, offset, period, clock)
	}
}

func (h *harness) expectIdle() {
	h.t.Helper()
	st, err := h.b.Status(h.t.Context())
	if err != nil {
		h.t.Fatal(err)
	}
	if st.State != schema.BroadcastStatusStateIdle || st.Speed != DefaultSpeed || st.MatchID != nil {
		h.t.Errorf("status = %+v, want idle at default speed", st)
	}
}

func describe(msg schema.FeedMessage) string {
	if msg.Event != nil {
		return "event " + msg.Event.ID
	}
	m := msg.Marker
	s := fmt.Sprintf("%s m%d %d (%d, %g)", msg.Kind, m.MatchID, m.Offset, m.Period, m.MatchClockS)
	if m.Head != nil {
		s += fmt.Sprintf(" head %d", *m.Head)
	}
	return s
}

// roundTrip checks that v survives JSON encoding and the generated decoder,
// which enforces the JSON Schema.
func roundTrip[T any](t *testing.T, v *T) {
	t.Helper()
	data, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	var back T
	if err := json.Unmarshal(data, &back); err != nil {
		t.Fatalf("violates schema: %v\n%s", err, data)
	}
}

func deref[T any](p *T) any {
	if p == nil {
		return nil
	}
	return *p
}
