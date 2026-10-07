package statsbomb

import (
	"fmt"
	"sort"
	"strconv"
	"strings"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
)

// periodStartMs is the game clock at the start of each period. StatsBomb
// timestamps restart at 00:00 every period, so match_clock_s = start + timestamp.
var periodStartMs = map[int]int64{
	1: 0,               // first half
	2: 45 * 60 * 1000,  // second half
	3: 90 * 60 * 1000,  // extra time, first half
	4: 105 * 60 * 1000, // extra time, second half
	5: 120 * 60 * 1000, // penalty shootout
}

// eventTypes maps StatsBomb type names to ours. Anything else (Starting XI,
// Tactical Shift, Injury Stoppage, Own Goal For/Against, ...) becomes "other".
var eventTypes = map[string]schema.MatchEventType{
	"Pass":           schema.MatchEventTypePass,
	"Carry":          schema.MatchEventTypeCarry,
	"Shot":           schema.MatchEventTypeShot,
	"Ball Receipt*":  schema.MatchEventTypeBallReceipt,
	"Ball Recovery":  schema.MatchEventTypeBallRecovery,
	"Interception":   schema.MatchEventTypeInterception,
	"Duel":           schema.MatchEventTypeDuel,
	"Dribble":        schema.MatchEventTypeDribble,
	"Dribbled Past":  schema.MatchEventTypeDribbledPast,
	"Clearance":      schema.MatchEventTypeClearance,
	"Block":          schema.MatchEventTypeBlock,
	"Pressure":       schema.MatchEventTypePressure,
	"Foul Committed": schema.MatchEventTypeFoulCommitted,
	"Foul Won":       schema.MatchEventTypeFoulWon,
	"Miscontrol":     schema.MatchEventTypeMiscontrol,
	"Dispossessed":   schema.MatchEventTypeDispossessed,
	"Goal Keeper":    schema.MatchEventTypeGoalkeeper,
	"50/50":          schema.MatchEventTypeFiftyFifty,
	"Offside":        schema.MatchEventTypeOffside,
	"Substitution":   schema.MatchEventTypeSubstitution,
	"Half Start":     schema.MatchEventTypeHalfStart,
	"Half End":       schema.MatchEventTypeHalfEnd,
}

// contestOutcomes classifies outcomes of duels, dribbles, interceptions and
// 50/50s. Names not listed here produce no outcome.
var contestOutcomes = map[string]schema.MatchEventOutcome{
	"Complete":              schema.MatchEventOutcomeSuccess,
	"Won":                   schema.MatchEventOutcomeSuccess,
	"Success":               schema.MatchEventOutcomeSuccess,
	"Success In Play":       schema.MatchEventOutcomeSuccess,
	"Success Out":           schema.MatchEventOutcomeSuccess,
	"Success To Team":       schema.MatchEventOutcomeSuccess,
	"Incomplete":            schema.MatchEventOutcomeFailure,
	"Lost":                  schema.MatchEventOutcomeFailure,
	"Lost In Play":          schema.MatchEventOutcomeFailure,
	"Lost Out":              schema.MatchEventOutcomeFailure,
	"Success To Opposition": schema.MatchEventOutcomeFailure,
}

var shotOutcomes = map[string]schema.MatchEventShotOutcome{
	"Goal":             schema.MatchEventShotOutcomeGoal,
	"Saved":            schema.MatchEventShotOutcomeSaved,
	"Saved Off Target": schema.MatchEventShotOutcomeSaved,
	"Saved to Post":    schema.MatchEventShotOutcomeSaved,
	"Blocked":          schema.MatchEventShotOutcomeBlocked,
	"Off T":            schema.MatchEventShotOutcomeOffTarget,
	"Wayward":          schema.MatchEventShotOutcomeOffTarget,
	"Post":             schema.MatchEventShotOutcomePost,
}

// Normalize converts raw StatsBomb events into feed events.
//
// Feed order is StatsBomb's own `index` order, not a re-sort by timestamp: the
// provider occasionally records an event a fraction of a second "earlier" than
// the one before it, exactly like a real live feed, and the engine's reorder
// buffer is responsible for coping with that. Offsets are assigned 0..n-1 in
// that order.
func Normalize(matchID int, raws []rawEvent) ([]schema.MatchEvent, error) {
	// Sort a copy so the caller's slice is left untouched.
	sorted := make([]rawEvent, len(raws))
	copy(sorted, raws)
	sort.SliceStable(sorted, func(i, j int) bool { return sorted[i].Index < sorted[j].Index })

	events := make([]schema.MatchEvent, 0, len(sorted))
	for i, r := range sorted {
		ev, err := normalizeEvent(matchID, i, r)
		if err != nil {
			return nil, fmt.Errorf("event %d (%s): %w", r.Index, r.ID, err)
		}
		events = append(events, ev)
	}
	return events, nil
}

func normalizeEvent(matchID, offset int, r rawEvent) (schema.MatchEvent, error) {
	if r.ID == "" {
		return schema.MatchEvent{}, fmt.Errorf("missing id")
	}
	if r.Team == nil {
		return schema.MatchEvent{}, fmt.Errorf("missing team")
	}
	start, ok := periodStartMs[r.Period]
	if !ok {
		return schema.MatchEvent{}, fmt.Errorf("unknown period %d", r.Period)
	}
	tsMs, err := parseTimestampMs(r.Timestamp)
	if err != nil {
		return schema.MatchEvent{}, err
	}

	ev := schema.MatchEvent{
		SchemaVersion: 1,
		ID:            r.ID,
		MatchID:       schema.MatchID(matchID),
		Offset:        schema.Offset(offset),
		Period:        schema.Period(r.Period),
		// Whole milliseconds divided once, so 2700 + 2100.474 is exactly 4800.474
		// rather than accumulating floating-point error.
		MatchClockS:      schema.MatchClockSeconds(float64(start+tsMs) / 1000),
		Type:             eventType(r.Type.Name),
		Team:             schema.Team{ID: r.Team.ID, Name: r.Team.Name},
		PossessionID:     r.Possession,
		PossessionTeamID: r.PossessionTeam.ID,
		Location:         point(r.Location),
		Outcome:          outcome(r),
	}
	if r.Player != nil {
		ev.Player = &schema.Player{ID: r.Player.ID, Name: r.Player.Name}
	}

	switch {
	case r.Pass != nil:
		ev.EndLocation = point(r.Pass.EndLocation)
	case r.Carry != nil:
		ev.EndLocation = point(r.Carry.EndLocation)
	case r.Shot != nil:
		ev.EndLocation = point(r.Shot.EndLocation)
		ev.Shot = &schema.ShotDetail{XG: r.Shot.XG, Outcome: shotOutcome(r.Shot.Outcome)}
	}
	return ev, nil
}

func eventType(name string) schema.MatchEventType {
	if t, ok := eventTypes[name]; ok {
		return t
	}
	return schema.MatchEventTypeOther
}

// outcome returns nil when the event type has no success/failure notion or the
// provider did not record one; the field is then omitted from the JSON.
func outcome(r rawEvent) *schema.MatchEventOutcome {
	var o schema.MatchEventOutcome
	switch {
	case r.Pass != nil:
		// StatsBomb omits the outcome for completed passes; any outcome
		// (Incomplete, Out, Pass Offside, Unknown, ...) means it failed.
		o = schema.MatchEventOutcomeSuccess
		if r.Pass.Outcome != nil {
			o = schema.MatchEventOutcomeFailure
		}
	case r.Type.Name == "Ball Receipt*":
		// Same convention: a ball_receipt object with an outcome means it failed.
		o = schema.MatchEventOutcomeSuccess
		if r.BallReceipt != nil && r.BallReceipt.Outcome != nil {
			o = schema.MatchEventOutcomeFailure
		}
	case r.Duel != nil:
		if r.Duel.Outcome == nil {
			if r.Duel.Type != nil && r.Duel.Type.Name == "Aerial Lost" {
				o = schema.MatchEventOutcomeFailure
				break
			}
			return nil
		}
		return contestOutcome(r.Duel.Outcome)
	case r.Dribble != nil:
		return contestOutcome(r.Dribble.Outcome)
	case r.Interception != nil:
		return contestOutcome(r.Interception.Outcome)
	case r.FiftyFifty != nil:
		return contestOutcome(r.FiftyFifty.Outcome)
	default:
		return nil
	}
	return &o
}

func contestOutcome(n *named) *schema.MatchEventOutcome {
	if n == nil {
		return nil
	}
	if o, ok := contestOutcomes[n.Name]; ok {
		return &o
	}
	return nil
}

func shotOutcome(n *named) schema.MatchEventShotOutcome {
	if n != nil {
		if o, ok := shotOutcomes[n.Name]; ok {
			return o
		}
	}
	return schema.MatchEventShotOutcomeOther
}

// point keeps [x, y] and drops a shot's height (z). Missing or malformed
// coordinates yield nil, which omits the field.
func point(c []float64) schema.Point {
	if len(c) < 2 {
		return nil
	}
	return schema.Point{c[0], c[1]}
}

// parseTimestampMs parses "HH:MM:SS.mmm" into whole milliseconds.
func parseTimestampMs(ts string) (int64, error) {
	parts := strings.Split(ts, ":")
	if len(parts) != 3 {
		return 0, fmt.Errorf("bad timestamp %q", ts)
	}
	h, errH := strconv.ParseInt(parts[0], 10, 64)
	m, errM := strconv.ParseInt(parts[1], 10, 64)
	s, errS := strconv.ParseFloat(parts[2], 64)
	if errH != nil || errM != nil || errS != nil || h < 0 || m < 0 || m >= 60 || s < 0 || s >= 60 {
		return 0, fmt.Errorf("bad timestamp %q", ts)
	}
	return (h*3600+m*60)*1000 + int64(s*1000+0.5), nil
}
