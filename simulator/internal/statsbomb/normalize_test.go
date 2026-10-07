package statsbomb

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
)

func TestParseTimestampMs(t *testing.T) {
	tests := []struct {
		in      string
		want    int64
		wantErr bool
	}{
		{in: "00:00:00.000", want: 0},
		{in: "00:04:40.798", want: 280798},
		{in: "01:02:03.004", want: 3723004},
		{in: "00:59:59.999", want: 3599999},
		{in: "00:00:01", want: 1000},
		{in: "", wantErr: true},
		{in: "00:00", wantErr: true},
		{in: "00:60:00.000", wantErr: true},
		{in: "00:00:60.000", wantErr: true},
		{in: "aa:00:00.000", wantErr: true},
		{in: "-1:00:00.000", wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.in, func(t *testing.T) {
			got, err := parseTimestampMs(tt.in)
			if tt.wantErr {
				if err == nil {
					t.Fatalf("expected error, got %d", got)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if got != tt.want {
				t.Errorf("got %d, want %d", got, tt.want)
			}
		})
	}
}

// base is a minimal valid raw event; test cases append type-specific JSON.
const base = `"id": "x", "index": 1, "possession": 3,
	"possession_team": {"id": 1, "name": "Home FC"},
	"team": {"id": 1, "name": "Home FC"}`

func TestNormalizeEvent(t *testing.T) {
	success := schema.MatchEventOutcomeSuccess
	failure := schema.MatchEventOutcomeFailure

	tests := []struct {
		name        string
		raw         string // JSON object body, combined with base
		wantType    schema.MatchEventType
		wantClock   float64
		wantOutcome *schema.MatchEventOutcome
		wantEnd     schema.Point
		wantShot    *schema.ShotDetail
	}{
		{
			name:        "completed pass has no provider outcome",
			raw:         `"period": 1, "timestamp": "00:10:00.000", "type": {"name": "Pass"}, "location": [10, 20], "pass": {"end_location": [30, 40]}`,
			wantType:    schema.MatchEventTypePass,
			wantClock:   600,
			wantOutcome: &success,
			wantEnd:     schema.Point{30, 40},
		},
		{
			name:        "any pass outcome is a failure",
			raw:         `"period": 2, "timestamp": "00:35:00.474", "type": {"name": "Pass"}, "pass": {"end_location": [1, 2], "outcome": {"name": "Out"}}`,
			wantType:    schema.MatchEventTypePass,
			wantClock:   4800.474,
			wantOutcome: &failure,
			wantEnd:     schema.Point{1, 2},
		},
		{
			name:     "shot keeps xg, maps outcome and drops height",
			raw:      `"period": 2, "timestamp": "00:35:59.025", "type": {"name": "Shot"}, "shot": {"statsbomb_xg": 0.1, "end_location": [120, 41.5, 0.4], "outcome": {"name": "Off T"}}`,
			wantType: schema.MatchEventTypeShot,
			// 45:00 + 35:59.025 = 80:59.025, Mbappé's second goal in the 2022 final.
			wantClock: 4859.025,
			wantEnd:   schema.Point{120, 41.5},
			wantShot:  &schema.ShotDetail{XG: 0.1, Outcome: schema.MatchEventShotOutcomeOffTarget},
		},
		{
			name:      "unknown shot outcome becomes other",
			raw:       `"period": 1, "timestamp": "00:00:01.000", "type": {"name": "Shot"}, "shot": {"statsbomb_xg": 0.5, "outcome": {"name": "Something New"}}`,
			wantType:  schema.MatchEventTypeShot,
			wantClock: 1,
			wantShot:  &schema.ShotDetail{XG: 0.5, Outcome: schema.MatchEventShotOutcomeOther},
		},
		{
			name:        "clean ball receipt has no ball_receipt object",
			raw:         `"period": 3, "timestamp": "00:01:00.000", "type": {"name": "Ball Receipt*"}`,
			wantType:    schema.MatchEventTypeBallReceipt,
			wantClock:   90*60 + 60,
			wantOutcome: &success,
		},
		{
			name:        "incomplete ball receipt",
			raw:         `"period": 4, "timestamp": "00:00:00.000", "type": {"name": "Ball Receipt*"}, "ball_receipt": {"outcome": {"name": "Incomplete"}}`,
			wantType:    schema.MatchEventTypeBallReceipt,
			wantClock:   105 * 60,
			wantOutcome: &failure,
		},
		{
			name:        "duel won",
			raw:         `"period": 1, "timestamp": "00:00:00.000", "type": {"name": "Duel"}, "duel": {"type": {"name": "Tackle"}, "outcome": {"name": "Won"}}`,
			wantType:    schema.MatchEventTypeDuel,
			wantOutcome: &success,
		},
		{
			name:        "aerial lost has no outcome but is a failure",
			raw:         `"period": 1, "timestamp": "00:00:00.000", "type": {"name": "Duel"}, "duel": {"type": {"name": "Aerial Lost"}}`,
			wantType:    schema.MatchEventTypeDuel,
			wantOutcome: &failure,
		},
		{
			name:        "dribble incomplete",
			raw:         `"period": 1, "timestamp": "00:00:00.000", "type": {"name": "Dribble"}, "dribble": {"outcome": {"name": "Incomplete"}}`,
			wantType:    schema.MatchEventTypeDribble,
			wantOutcome: &failure,
		},
		{
			name:        "50/50 lost to opposition",
			raw:         `"period": 1, "timestamp": "00:00:00.000", "type": {"name": "50/50"}, "50_50": {"outcome": {"name": "Success To Opposition"}}`,
			wantType:    schema.MatchEventTypeFiftyFifty,
			wantOutcome: &failure,
		},
		{
			name:        "interception with unrecognised outcome has none",
			raw:         `"period": 1, "timestamp": "00:00:00.000", "type": {"name": "Interception"}, "interception": {"outcome": {"name": "Brand New"}}`,
			wantType:    schema.MatchEventTypeInterception,
			wantOutcome: nil,
		},
		{
			name:      "carry end location",
			raw:       `"period": 1, "timestamp": "00:00:00.000", "type": {"name": "Carry"}, "carry": {"end_location": [5, 6]}`,
			wantType:  schema.MatchEventTypeCarry,
			wantEnd:   schema.Point{5, 6},
			wantClock: 0,
		},
		{
			name:     "unmapped type becomes other",
			raw:      `"period": 5, "timestamp": "00:00:00.000", "type": {"name": "Tactical Shift"}`,
			wantType: schema.MatchEventTypeOther, wantClock: 7200,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := decodeRaw(t, tt.raw)
			ev, err := normalizeEvent(42, 7, r)
			if err != nil {
				t.Fatal(err)
			}
			if ev.Type != tt.wantType {
				t.Errorf("type = %q, want %q", ev.Type, tt.wantType)
			}
			if float64(ev.MatchClockS) != tt.wantClock {
				t.Errorf("match_clock_s = %v, want %v", ev.MatchClockS, tt.wantClock)
			}
			if !reflect.DeepEqual(ev.Outcome, tt.wantOutcome) {
				t.Errorf("outcome = %v, want %v", deref(ev.Outcome), deref(tt.wantOutcome))
			}
			if !reflect.DeepEqual(ev.EndLocation, tt.wantEnd) {
				t.Errorf("end_location = %v, want %v", ev.EndLocation, tt.wantEnd)
			}
			if !reflect.DeepEqual(ev.Shot, tt.wantShot) {
				t.Errorf("shot = %+v, want %+v", ev.Shot, tt.wantShot)
			}
			if ev.MatchID != 42 || ev.Offset != 7 || ev.SchemaVersion != 1 {
				t.Errorf("match_id/offset/schema_version = %d/%d/%d", ev.MatchID, ev.Offset, ev.SchemaVersion)
			}
			assertSchemaValid(t, ev)
		})
	}
}

func TestNormalizeEventErrors(t *testing.T) {
	tests := map[string]string{
		"missing id":     `{"index": 1, "period": 1, "timestamp": "00:00:00.000", "type": {"name": "Pass"}, "team": {"id": 1, "name": "A"}}`,
		"missing team":   `{"id": "x", "index": 1, "period": 1, "timestamp": "00:00:00.000", "type": {"name": "Pass"}}`,
		"unknown period": `{"id": "x", "index": 1, "period": 6, "timestamp": "00:00:00.000", "type": {"name": "Pass"}, "team": {"id": 1, "name": "A"}}`,
		"bad timestamp":  `{"id": "x", "index": 1, "period": 1, "timestamp": "soon", "type": {"name": "Pass"}, "team": {"id": 1, "name": "A"}}`,
	}
	for name, raw := range tests {
		t.Run(name, func(t *testing.T) {
			var r rawEvent
			if err := json.Unmarshal([]byte(raw), &r); err != nil {
				t.Fatal(err)
			}
			if _, err := normalizeEvent(1, 0, r); err == nil {
				t.Error("expected error")
			}
		})
	}
}

func TestNormalizeUsesIndexOrderAndAssignsOffsets(t *testing.T) {
	raws := []rawEvent{
		{ID: "c", Index: 30, Period: 1, Timestamp: "00:00:05.000", Team: &named{ID: 1}},
		{ID: "a", Index: 10, Period: 1, Timestamp: "00:00:01.000", Team: &named{ID: 1}},
		// Index order puts "b" after "a" although its timestamp is earlier:
		// Normalize must keep the provider's order, not re-sort by time.
		{ID: "b", Index: 20, Period: 1, Timestamp: "00:00:00.500", Team: &named{ID: 1}},
	}
	events, err := Normalize(9, raws)
	if err != nil {
		t.Fatal(err)
	}
	var ids []string
	for i, ev := range events {
		ids = append(ids, ev.ID)
		if int(ev.Offset) != i {
			t.Errorf("event %s offset = %d, want %d", ev.ID, ev.Offset, i)
		}
	}
	if got := strings.Join(ids, ","); got != "a,b,c" {
		t.Errorf("order = %s, want a,b,c", got)
	}
	if raws[0].ID != "c" {
		t.Error("Normalize must not reorder the caller's slice")
	}
}

func decodeRaw(t *testing.T, body string) rawEvent {
	t.Helper()
	var r rawEvent
	if err := json.Unmarshal([]byte("{"+base+", "+body+"}"), &r); err != nil {
		t.Fatalf("decode test input: %v", err)
	}
	return r
}

// assertSchemaValid round-trips ev through JSON and the generated
// UnmarshalJSON, which enforces the JSON Schema's required fields and ranges.
func assertSchemaValid(t *testing.T, ev schema.MatchEvent) {
	t.Helper()
	data, err := json.Marshal(ev)
	if err != nil {
		t.Fatal(err)
	}
	var back schema.MatchEvent
	if err := json.Unmarshal(data, &back); err != nil {
		t.Fatalf("event violates schema: %v\n%s", err, data)
	}
	if !reflect.DeepEqual(back, ev) {
		t.Fatalf("round trip changed event:\n got %+v\nwant %+v", back, ev)
	}
}

func deref[T any](p *T) any {
	if p == nil {
		return nil
	}
	return *p
}
