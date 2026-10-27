// Package mapper turns Sportmonks fixtures, as the live feed sends them poll
// after poll, into the canonical feed: a match_start, the match's events in
// the order they became known, and a match_end.
//
// Sportmonks sends far less than a StatsBomb replay: goals, own goals,
// penalties, cards and substitutions, each to the minute, and when each half
// started and ended. So the feed has those and nothing else:
//
//   - a goal is a shot with outcome goal (penalty or open play), without xG;
//     the side that scored comes from the running score after it ("2-1"),
//     which also settles own goals;
//   - a missed penalty is a penalty shot, saved if Sportmonks says so;
//   - a card is a foul_committed with the card if it was for a foul, otherwise
//     an other;
//   - a substitution's player is the one going off;
//   - each half's start and end, for both teams (home first, so the engine
//     sees the teams in that order);
//   - a goal that disappears from the feed or is rescinded, typically after
//     VAR, becomes a goal_disallowed for it.
//
// An event's clock is its minute (with stoppage time), and within the minute,
// when the fixture is live, how far into the period the poll that first had
// it came (an event can't be later than when it arrived); otherwise the
// middle of the minute.
package mapper

import (
	"cmp"
	"encoding/json"
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/carsuelos/football-analytics-stream/livefeed/internal/schema"
)

// Sportmonks' type ids (GET /core/types).
const (
	typeGoal          = 14
	typeOwnGoal       = 15
	typePenalty       = 16
	typeMissedPenalty = 17
	typeSubstitution  = 18
	typeYellow        = 19
	typeRed           = 20
	typeYellowRed     = 21

	subFoul         = 1496
	subPenaltySaved = 1509

	periodPenalties = 5
)

// ended are the fixture states after which nothing more happens: full time,
// after extra time, after penalties.
var ended = map[int]bool{5: true, 7: true, 8: true}

// clockBase is where each period's clock starts, in seconds.
var clockBase = map[int]float64{1: 0, 2: 45 * 60, 3: 90 * 60, 4: 105 * 60, 5: 120 * 60}

// Fixture is the part of a Sportmonks fixture the mapper reads.
type Fixture struct {
	ID           int    `json:"id"`
	Name         string `json:"name"`
	StartingAt   string `json:"starting_at"`
	StateID      int    `json:"state_id"`
	LeagueID     int    `json:"league_id"`
	Participants []struct {
		ID   int    `json:"id"`
		Name string `json:"name"`
		Meta struct {
			Location string `json:"location"`
		} `json:"meta"`
	} `json:"participants"`
	Periods []Period `json:"periods"`
	Events  []Event  `json:"events"`
	Scores  []struct {
		ParticipantID int `json:"participant_id"`
		Score         struct {
			Goals int `json:"goals"`
		} `json:"score"`
		Description string `json:"description"`
	} `json:"scores"`
	League *struct {
		Name string `json:"name"`
	} `json:"league"`
	Season *struct {
		Name string `json:"name"`
	} `json:"season"`
}

// Period is a half (or extra time, or the shootout).
type Period struct {
	ID        int    `json:"id"`
	TypeID    int    `json:"type_id"`
	Started   *int64 `json:"started"`
	Ended     *int64 `json:"ended"`
	Ticking   bool   `json:"ticking"`
	SortOrder int    `json:"sort_order"`
}

// Event is something that happened, to the minute.
type Event struct {
	ID                int     `json:"id"`
	PeriodID          int     `json:"period_id"`
	ParticipantID     int     `json:"participant_id"`
	TypeID            int     `json:"type_id"`
	SubTypeID         *int    `json:"sub_type_id"`
	PlayerID          *int    `json:"player_id"`
	PlayerName        *string `json:"player_name"`
	RelatedPlayerID   *int    `json:"related_player_id"`
	RelatedPlayerName *string `json:"related_player_name"`
	Result            *string `json:"result"`
	Minute            int     `json:"minute"`
	ExtraMinute       *int    `json:"extra_minute"`
	SortOrder         *int    `json:"sort_order"`
	Rescinded         *bool   `json:"rescinded"`
}

func (e Event) rescinded() bool { return e.Rescinded != nil && *e.Rescinded }

func isGoal(typeID int) bool {
	return typeID == typeGoal || typeID == typeOwnGoal || typeID == typePenalty
}

// Mapper maps one fixture's polls. Create it with New.
type Mapper struct {
	matchID    int
	home, away *schema.Team
	offset     int
	started    bool
	finished   bool
	emitted    map[int]bool // Sportmonks event ids already in the feed
	goals      map[int]goal // goals in the feed, by Sportmonks event id
	halves     map[string]bool
	last       schema.FeedMarker
}

type goal struct {
	eventID string
	team    schema.Team
	period  int
	clock   float64
}

// New returns a mapper for a fixture.
func New(fixtureID int) *Mapper {
	return &Mapper{matchID: fixtureID, emitted: map[int]bool{}, goals: map[int]goal{}, halves: map[string]bool{}}
}

// item is a feed event before it has an offset, with what orders it.
type item struct {
	period int
	rank   int // 0 a half's start, 1 an event, 2 a half's end
	clock  float64
	order  int
	id     int
	event  schema.MatchEvent
}

// Next maps a poll of the fixture, received at receivedAt, to the feed
// messages it adds.
func (m *Mapper) Next(raw json.RawMessage, receivedAt time.Time) ([]schema.FeedMessage, error) {
	var f Fixture
	if err := json.Unmarshal(raw, &f); err != nil {
		return nil, fmt.Errorf("mapper: fixture: %w", err)
	}
	if f.ID != m.matchID {
		return nil, fmt.Errorf("mapper: fixture %d given to the mapper for %d", f.ID, m.matchID)
	}
	if m.finished {
		return nil, nil
	}
	if m.home == nil {
		var home, away *schema.Team
		for _, p := range f.Participants {
			t := &schema.Team{ID: p.ID, Name: p.Name}
			switch p.Meta.Location {
			case "home":
				home = t
			case "away":
				away = t
			}
		}
		if home == nil || away == nil {
			return nil, nil // the teams aren't known yet
		}
		m.home, m.away = home, away
	}
	periods := map[int]Period{}
	for _, p := range f.Periods {
		periods[p.ID] = p
	}

	var items []item
	for _, p := range f.Periods {
		n := periodNumber(p)
		if n == periodPenalties || p.Started == nil {
			continue
		}
		items = append(items, m.half(n, schema.MatchEventTypeHalfStart, clockBase[n])...)
		if p.Ended != nil {
			items = append(items, m.half(n, schema.MatchEventTypeHalfEnd, clockBase[n]+float64(*p.Ended-*p.Started))...)
		}
	}
	scorers := m.scorers(f.Events)
	for _, e := range f.Events {
		if m.emitted[e.ID] || e.rescinded() {
			continue
		}
		if it, ok := m.event(e, periods, scorers, receivedAt); ok {
			m.emitted[e.ID] = true
			items = append(items, it)
		}
	}
	items = append(items, m.cancelled(f.Events)...)

	slices.SortStableFunc(items, func(a, b item) int {
		return cmp.Or(cmp.Compare(a.period, b.period), cmp.Compare(a.rank, b.rank),
			cmp.Compare(a.clock, b.clock), cmp.Compare(a.order, b.order), cmp.Compare(a.id, b.id))
	})
	var out []schema.FeedMessage
	if !m.started && len(items) > 0 {
		m.started = true
		head := schema.Offset(0)
		out = append(out, schema.FeedMessage{SchemaVersion: 1, Kind: schema.FeedMessageKindMatchStart,
			Marker: &schema.FeedMarker{MatchID: schema.MatchID(m.matchID), Period: 1, Head: &head}})
	}
	for _, it := range items {
		ev := it.event
		ev.SchemaVersion = 1
		ev.MatchID = schema.MatchID(m.matchID)
		ev.Offset = schema.Offset(m.offset)
		ev.Period = schema.Period(it.period)
		ev.MatchClockS = schema.MatchClockSeconds(it.clock)
		ev.PossessionID = m.offset
		ev.PossessionTeamID = ev.Team.ID
		m.offset++
		m.last = schema.FeedMarker{MatchID: ev.MatchID, Offset: schema.Offset(m.offset), Period: ev.Period, MatchClockS: ev.MatchClockS}
		out = append(out, schema.FeedMessage{SchemaVersion: 1, Kind: schema.FeedMessageKindEvent, Event: &ev})
	}
	if ended[f.StateID] && m.started {
		m.finished = true
		end := m.last
		out = append(out, schema.FeedMessage{SchemaVersion: 1, Kind: schema.FeedMessageKindMatchEnd, Marker: &end})
	}
	return out, nil
}

// half is a half's start or end for both teams, home first, once.
func (m *Mapper) half(period int, t schema.MatchEventType, clock float64) []item {
	key := fmt.Sprintf("%d-%s", period, t)
	if m.halves[key] {
		return nil
	}
	m.halves[key] = true
	rank := 0
	if t == schema.MatchEventTypeHalfEnd {
		rank = 2
	}
	var items []item
	for i, team := range []schema.Team{*m.home, *m.away} {
		items = append(items, item{period: period, rank: rank, clock: clock, order: i, event: schema.MatchEvent{
			ID:   fmt.Sprintf("sm-%d-p%d-%s-%d", m.matchID, period, strings.TrimPrefix(string(t), "half_"), team.ID),
			Type: t, Team: team,
		}})
	}
	return items
}

// scorers works out which side each goal counted for, from the running score
// after it: the side whose count went up since the goal before.
func (m *Mapper) scorers(events []Event) map[int]schema.Team {
	var goals []Event
	for _, e := range events {
		if isGoal(e.TypeID) && !e.rescinded() && e.Result != nil {
			goals = append(goals, e)
		}
	}
	slices.SortStableFunc(goals, func(a, b Event) int {
		return cmp.Or(cmp.Compare(a.Minute+deref(a.ExtraMinute), b.Minute+deref(b.ExtraMinute)),
			cmp.Compare(deref(a.SortOrder), deref(b.SortOrder)), cmp.Compare(a.ID, b.ID))
	})
	out := map[int]schema.Team{}
	var prev [2]int
	for _, e := range goals {
		h, a, ok := parseResult(*e.Result)
		if !ok {
			continue
		}
		switch {
		case h > prev[0] && a == prev[1]:
			out[e.ID] = *m.home
		case a > prev[1] && h == prev[0]:
			out[e.ID] = *m.away
		}
		prev = [2]int{h, a}
	}
	return out
}

// event maps a Sportmonks event; ok is false for the kinds the feed doesn't carry.
func (m *Mapper) event(e Event, periods map[int]Period, scorers map[int]schema.Team, receivedAt time.Time) (item, bool) {
	team, known := m.team(e.ParticipantID)
	ev := schema.MatchEvent{ID: fmt.Sprintf("sm-%d", e.ID), Team: team, Player: player(e.PlayerID, e.PlayerName)}
	scorer, scored := scorers[e.ID]
	switch e.TypeID {
	case typeGoal, typePenalty:
		if scored {
			ev.Team = scorer
		} else if !known {
			return item{}, false
		}
		st := schema.MatchEventShotTypeOpenPlay
		if e.TypeID == typePenalty {
			st = schema.MatchEventShotTypePenalty
		}
		ev.Type, ev.Shot = schema.MatchEventTypeShot, &schema.ShotDetail{Outcome: schema.MatchEventShotOutcomeGoal, Type: &st}
	case typeOwnGoal:
		// team is the side that put the ball into its own net, not the one it counted for.
		if scored {
			ev.Team = m.other(scorer)
		} else if !known {
			return item{}, false
		}
		ev.Type = schema.MatchEventTypeOwnGoal
	case typeMissedPenalty:
		st, outcome := schema.MatchEventShotTypePenalty, schema.MatchEventShotOutcomeOther
		if deref(e.SubTypeID) == subPenaltySaved {
			outcome = schema.MatchEventShotOutcomeSaved
		}
		ev.Type, ev.Shot = schema.MatchEventTypeShot, &schema.ShotDetail{Outcome: outcome, Type: &st}
	case typeYellow, typeRed, typeYellowRed:
		c := map[int]schema.MatchEventCard{
			typeYellow: schema.MatchEventCardYellow, typeRed: schema.MatchEventCardRed, typeYellowRed: schema.MatchEventCardSecondYellow,
		}[e.TypeID]
		ev.Card, ev.Type = &c, schema.MatchEventTypeOther
		if deref(e.SubTypeID) == subFoul {
			ev.Type = schema.MatchEventTypeFoulCommitted
		}
	case typeSubstitution:
		// Sportmonks' player is the one coming on; the feed's is the one going off.
		ev.Type, ev.Player = schema.MatchEventTypeSubstitution, player(e.RelatedPlayerID, e.RelatedPlayerName)
	default:
		return item{}, false
	}
	if !known && !isGoal(e.TypeID) {
		return item{}, false
	}
	period := eventPeriod(e, periods)
	floor := minuteClock(e, period)
	clock := floor + 30
	if p, ok := periods[e.PeriodID]; ok && p.Started != nil {
		switch {
		case p.Ended != nil:
			// Never after the half ended: the middle of 90+5 can be past it.
			clock = min(clock, clockBase[period]+float64(*p.Ended-*p.Started))
		case p.Ticking && !receivedAt.IsZero():
			elapsed := clockBase[period] + receivedAt.Sub(time.Unix(*p.Started, 0)).Seconds()
			clock = min(max(elapsed, floor), floor+59)
		}
	}
	if isGoal(e.TypeID) {
		m.goals[e.ID] = goal{eventID: ev.ID, team: ev.Team, period: period, clock: clock}
	}
	return item{period: period, rank: 1, clock: clock, order: deref(e.SortOrder), id: e.ID, event: ev}, true
}

// cancelled are goal_disallowed events for goals in the feed that have since
// disappeared from it or been rescinded.
func (m *Mapper) cancelled(events []Event) []item {
	present := map[int]Event{}
	for _, e := range events {
		present[e.ID] = e
	}
	var items []item
	for id, g := range m.goals {
		if e, ok := present[id]; ok && !e.rescinded() {
			continue
		}
		delete(m.goals, id)
		items = append(items, item{period: g.period, rank: 1, clock: g.clock, order: 1 << 30, id: id, event: schema.MatchEvent{
			ID: fmt.Sprintf("sm-%d-disallowed", id), Type: schema.MatchEventTypeGoalDisallowed, Team: g.team,
			DisallowedGoal: &schema.DisallowedGoal{EventID: g.eventID, Reason: schema.DisallowedReasonOther},
		}})
	}
	return items
}

func (m *Mapper) team(participant int) (schema.Team, bool) {
	switch participant {
	case m.home.ID:
		return *m.home, true
	case m.away.ID:
		return *m.away, true
	}
	return schema.Team{}, false
}

func (m *Mapper) other(t schema.Team) schema.Team {
	if t.ID == m.home.ID {
		return *m.away
	}
	return *m.home
}

// eventPeriod is the event's period number, from its period id, or else from
// its minute.
func eventPeriod(e Event, periods map[int]Period) int {
	if p, ok := periods[e.PeriodID]; ok {
		return periodNumber(p)
	}
	switch {
	case e.Minute <= 45:
		return 1
	case e.Minute <= 90:
		return 2
	case e.Minute <= 105:
		return 3
	}
	return 4
}

// periodNumber is the feed's period: 1 and 2 the halves, 3 and 4 extra time, 5 the shootout.
func periodNumber(p Period) int {
	if p.TypeID == periodPenalties {
		return periodPenalties
	}
	return min(max(p.SortOrder, 1), 4)
}

// minuteClock is the start of the event's minute: minute 17 is 16:00 to 17:00,
// and 45+2 is 46:00 to 47:00 of the first half.
func minuteClock(e Event, period int) float64 {
	return max(float64(e.Minute+deref(e.ExtraMinute)-1)*60, clockBase[period])
}

func player(id *int, name *string) *schema.Player {
	if id == nil || name == nil {
		return nil
	}
	return &schema.Player{ID: *id, Name: *name}
}

func parseResult(s string) (int, int, bool) {
	h, a, ok := strings.Cut(s, "-")
	if !ok {
		return 0, 0, false
	}
	hi, err1 := strconv.Atoi(strings.TrimSpace(h))
	ai, err2 := strconv.Atoi(strings.TrimSpace(a))
	return hi, ai, err1 == nil && err2 == nil
}

func deref(p *int) int {
	if p == nil {
		return 0
	}
	return *p
}

// Info describes the match for a MatchList, with the score as Sportmonks gives it.
func Info(raw json.RawMessage) (schema.MatchInfo, error) {
	var f Fixture
	if err := json.Unmarshal(raw, &f); err != nil {
		return schema.MatchInfo{}, fmt.Errorf("mapper: fixture: %w", err)
	}
	info := schema.MatchInfo{MatchID: schema.MatchID(f.ID), Competition: fmt.Sprintf("league %d", f.LeagueID)}
	if f.League != nil {
		info.Competition = f.League.Name
	}
	if f.Season != nil {
		info.Season = f.Season.Name
	}
	if len(f.StartingAt) >= 10 {
		info.Date = f.StartingAt[:10]
	}
	for _, p := range f.Participants {
		switch p.Meta.Location {
		case "home":
			info.HomeTeam = schema.Team{ID: p.ID, Name: p.Name}
		case "away":
			info.AwayTeam = schema.Team{ID: p.ID, Name: p.Name}
		}
	}
	for _, s := range f.Scores {
		if s.Description != "CURRENT" {
			continue
		}
		switch s.ParticipantID {
		case info.HomeTeam.ID:
			info.HomeScore = s.Score.Goals
		case info.AwayTeam.ID:
			info.AwayScore = s.Score.Goals
		}
	}
	return info, nil
}
