package mapper

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/carsuelos/football-analytics-stream/livefeed/internal/schema"
)

// kickoff is when the first half started, as Sportmonks gives it (Unix seconds).
const kickoff = int64(1792324800)

type ev struct {
	id, typ, sub, team, minute, extra int
	result                            string
	player, related                   string
	rescinded                         bool
}

type poll struct {
	state   int
	periods [][3]int64 // type, started, ended (0 for not yet)
	events  []ev
}

func (p poll) json(t *testing.T) json.RawMessage {
	t.Helper()
	var periods []map[string]any
	for i, pr := range p.periods {
		m := map[string]any{"id": 100 + i, "type_id": pr[0], "sort_order": i + 1, "started": pr[1], "ticking": pr[2] == 0}
		if pr[2] != 0 {
			m["ended"] = pr[2]
		}
		periods = append(periods, m)
	}
	var events []map[string]any
	for _, e := range p.events {
		m := map[string]any{"id": e.id, "type_id": e.typ, "participant_id": e.team, "minute": e.minute, "sort_order": 1, "period_id": 100}
		if e.minute > 45 && e.extra == 0 || len(p.periods) > 1 && e.minute > 45 {
			m["period_id"] = 101
		}
		if e.sub != 0 {
			m["sub_type_id"] = e.sub
		}
		if e.extra != 0 {
			m["extra_minute"] = e.extra
		}
		if e.result != "" {
			m["result"] = e.result
		}
		if e.player != "" {
			m["player_id"], m["player_name"] = 7, e.player
		}
		if e.related != "" {
			m["related_player_id"], m["related_player_name"] = 8, e.related
		}
		if e.rescinded {
			m["rescinded"] = true
		}
		events = append(events, m)
	}
	b, err := json.Marshal(map[string]any{
		"id": 42, "name": "Celtic vs Rangers", "state_id": p.state, "starting_at": "2026-10-31 12:00:00", "league_id": 501,
		"participants": []map[string]any{
			{"id": 53, "name": "Celtic", "meta": map[string]string{"location": "home"}},
			{"id": 62, "name": "Rangers", "meta": map[string]string{"location": "away"}},
		},
		"periods": periods, "events": events,
		"scores": []map[string]any{
			{"participant_id": 53, "description": "CURRENT", "score": map[string]int{"goals": 1}},
			{"participant_id": 62, "description": "CURRENT", "score": map[string]int{"goals": 0}},
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// line is a feed message in short: "kind" or "type team clock [detail]".
func line(m schema.FeedMessage) string {
	if m.Event == nil {
		return string(m.Kind)
	}
	e := m.Event
	s := fmt.Sprintf("%s %s %g", e.Type, e.Team.Name, float64(e.MatchClockS))
	switch {
	case e.Shot != nil:
		s += fmt.Sprintf(" %s/%s", e.Shot.Outcome, *e.Shot.Type)
	case e.Card != nil:
		s += " " + string(*e.Card)
	case e.DisallowedGoal != nil:
		s += " cancels " + e.DisallowedGoal.EventID
	case e.Type == schema.MatchEventTypeSubstitution && e.Player != nil:
		s += " off " + e.Player.Name
	}
	return s
}

func run(t *testing.T, m *Mapper, p poll, at time.Time) []string {
	t.Helper()
	msgs, err := m.Next(p.json(t), at)
	if err != nil {
		t.Fatal(err)
	}
	var out []string
	for i, msg := range msgs {
		out = append(out, line(msg))
		if msg.Event != nil && int(msg.Event.Offset) != m.offset-countEvents(msgs[i:]) {
			t.Errorf("offsets out of sequence at %q", line(msg))
		}
	}
	return out
}

func countEvents(msgs []schema.FeedMessage) int {
	n := 0
	for _, m := range msgs {
		if m.Event != nil {
			n++
		}
	}
	return n
}

func at(s int64) time.Time { return time.Unix(kickoff+s, 0) }

func expect(t *testing.T, got []string, want ...string) {
	t.Helper()
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Errorf("got:\n  %s\nwant:\n  %s", strings.Join(got, "\n  "), strings.Join(want, "\n  "))
	}
}

func TestAMatchAsItHappens(t *testing.T) {
	m := New(42)
	first := [3]int64{1, kickoff, 0}

	// Kick-off: both teams, home first, then the match's start.
	expect(t, run(t, m, poll{state: 2, periods: [][3]int64{first}}, at(5)),
		"match_start", "half_start Celtic 0", "half_start Rangers 0")

	// A goal in the 17th minute, polled 16:40 into the half: the clock is when it arrived.
	goal := ev{id: 1, typ: typeGoal, team: 53, minute: 17, result: "1-0", player: "Kyogo"}
	p := poll{state: 2, periods: [][3]int64{first}, events: []ev{goal}}
	expect(t, run(t, m, p, at(16*60+40)), "shot Celtic 1000 goal/open_play")
	// The same poll again adds nothing.
	expect(t, run(t, m, p, at(16*60+43)))

	// An own goal by a Rangers player: it counts for Celtic (2-0), and its team
	// is Rangers. A yellow card for a foul, and one for dissent. Polled after
	// their minutes ended, each is at the last second of its minute.
	og := ev{id: 2, typ: typeOwnGoal, team: 53, minute: 30, result: "2-0", player: "Goldson"}
	foul := ev{id: 3, typ: typeYellow, sub: subFoul, team: 62, minute: 31}
	dissent := ev{id: 4, typ: typeYellow, sub: 1497, team: 53, minute: 31}
	p.events = append(p.events, og, foul, dissent)
	expect(t, run(t, m, p, at(31*60+50)),
		"own_goal Rangers 1799", "foul_committed Rangers 1859 yellow", "other Celtic 1859 yellow")

	// A Rangers goal in the 40th minute polled 39:20 in, then VAR rules it out:
	// it disappears.
	ruledOut := ev{id: 5, typ: typeGoal, team: 62, minute: 40, result: "2-1"}
	p.events = append(p.events, ruledOut)
	expect(t, run(t, m, p, at(39*60+20)), "shot Rangers 2360 goal/open_play")
	p.events = p.events[:4]
	expect(t, run(t, m, p, at(41*60)), "goal_disallowed Rangers 2360 cancels sm-5")

	// Half time at 47:10, with a card in stoppage time (45+2) given the middle
	// of its minute but no later than the half's end.
	firstDone := [3]int64{1, kickoff, kickoff + 47*60 + 10}
	late := ev{id: 6, typ: typeRed, team: 62, minute: 45, extra: 2}
	p = poll{state: 3, periods: [][3]int64{firstDone}, events: append(p.events, late)}
	expect(t, run(t, m, p, at(48*60)), "other Rangers 2790 red", "half_end Celtic 2830", "half_end Rangers 2830")

	// The second half, a substitution (the feed's player is the one going off)
	// and full time, all in one poll: everything once, in order, then the end.
	secondStart := kickoff + 63*60
	second := [3]int64{2, secondStart, secondStart + 49*60}
	sub := ev{id: 7, typ: typeSubstitution, team: 53, minute: 60, player: "On", related: "Off"}
	p = poll{state: 5, periods: [][3]int64{firstDone, second}, events: append(p.events, sub)}
	expect(t, run(t, m, p, time.Unix(secondStart+60*60, 0)),
		"half_start Celtic 2700", "half_start Rangers 2700", "substitution Celtic 3570 off Off",
		"half_end Celtic 5640", "half_end Rangers 5640", "match_end")
	expect(t, run(t, m, p, time.Unix(secondStart+61*60, 0)))
}

func TestARescindedGoalIsCancelledAndAPenaltyGoalIsAPenalty(t *testing.T) {
	m := New(42)
	first := [3]int64{1, kickoff, 0}
	pen := ev{id: 1, typ: typePenalty, team: 62, minute: 10, result: "0-1"}
	missed := ev{id: 2, typ: typeMissedPenalty, sub: subPenaltySaved, team: 53, minute: 12}
	p := poll{state: 2, periods: [][3]int64{first}, events: []ev{pen, missed}}
	expect(t, run(t, m, p, at(12*60+30)),
		"match_start", "half_start Celtic 0", "half_start Rangers 0",
		"shot Rangers 599 goal/penalty", "shot Celtic 719 saved/penalty")
	pen.rescinded = true
	p.events = []ev{pen, missed}
	expect(t, run(t, m, p, at(13*60)), "goal_disallowed Rangers 599 cancels sm-1")
}

func TestNothingUntilBothTeamsAreKnown(t *testing.T) {
	m := New(42)
	msgs, err := m.Next(json.RawMessage(`{"id":42,"state_id":1,"participants":[]}`), at(0))
	if err != nil || len(msgs) != 0 {
		t.Errorf("msgs %v, err %v", msgs, err)
	}
	if _, err := m.Next(json.RawMessage(`{"id":43}`), at(0)); err == nil {
		t.Error("another fixture's poll should be an error")
	}
}

func TestInfo(t *testing.T) {
	info, err := Info(poll{state: 5}.json(t))
	if err != nil {
		t.Fatal(err)
	}
	want := schema.MatchInfo{MatchID: 42, Competition: "league 501", Date: "2026-10-31",
		HomeTeam: schema.Team{ID: 53, Name: "Celtic"}, AwayTeam: schema.Team{ID: 62, Name: "Rangers"}, HomeScore: 1}
	if info != want {
		t.Errorf("info %+v, want %+v", info, want)
	}
}
