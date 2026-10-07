package statsbomb

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
)

// Tests against the real 2022 World Cup final. StatsBomb data is never
// committed, so these skip unless `make fetch-data` has been run locally.

const (
	dataDir = "../../../data/statsbomb"
	finalID = 3869685
)

func loadFinal(t *testing.T) []schema.MatchEvent {
	t.Helper()
	if _, err := os.Stat(filepath.Join(dataDir, "events", "3869685.json")); err != nil {
		t.Skip("World Cup final not downloaded; run: make fetch-data ARGS=\"--match-id 3869685\"")
	}
	m, err := NewCatalog(dataDir).Load(finalID)
	if err != nil {
		t.Fatal(err)
	}
	if m.HomeTeam.Name != "Argentina" || m.AwayTeam.Name != "France" || m.HomeScore != 3 || m.AwayScore != 3 {
		t.Errorf("unexpected match info: %+v", m.Info)
	}
	return m.Events
}

func TestFinalEveryEventMatchesSchema(t *testing.T) {
	events := loadFinal(t)
	if len(events) != 4407 {
		t.Errorf("got %d events, want 4407", len(events))
	}
	for i, ev := range events {
		if int(ev.Offset) != i {
			t.Fatalf("event %s has offset %d, want %d", ev.ID, ev.Offset, i)
		}
		assertSchemaValid(t, ev)
	}
}

func TestFinalGoals(t *testing.T) {
	type goal struct {
		period int
		clock  string // mm:ss of match time
		team   string
	}
	// Open-play and penalty goals before the shootout (period 5).
	want := []goal{
		{1, "22:24", "Argentina"},  // Messi (pen)
		{1, "35:22", "Argentina"},  // Di María
		{2, "79:24", "France"},     // Mbappé (pen)
		{2, "80:59", "France"},     // Mbappé
		{4, "107:58", "Argentina"}, // Messi; extra time's second half starts at 105:00
		{4, "117:05", "France"},    // Mbappé (pen)
	}
	var got []goal
	for _, ev := range loadFinal(t) {
		if ev.Shot != nil && ev.Shot.Outcome == schema.MatchEventShotOutcomeGoal && ev.Period < 5 {
			s := int(ev.MatchClockS)
			got = append(got, goal{int(ev.Period), mmss(s), ev.Team.Name})
		}
	}
	if len(got) != len(want) {
		t.Fatalf("got %d goals %v, want %v", len(got), got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("goal %d = %v, want %v", i, got[i], want[i])
		}
	}
}

// The committed schema fixture shot_goal.json was taken from this match, so the
// normalizer must reproduce its identity and position fields exactly.
func TestFinalMatchesShotGoalFixture(t *testing.T) {
	events := loadFinal(t)
	data, err := os.ReadFile("../../../schema/fixtures/valid/event/shot_goal.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture schema.MatchEvent
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	got := events[fixture.Offset]
	if got.ID != fixture.ID || got.Period != fixture.Period || got.MatchClockS != fixture.MatchClockS ||
		got.Team != fixture.Team || got.Player == nil || *got.Player != *fixture.Player ||
		got.PossessionID != fixture.PossessionID {
		t.Errorf("offset %d:\n got %+v\nwant %+v", fixture.Offset, got, fixture)
	}
}

func mmss(seconds int) string {
	return fmt.Sprintf("%02d:%02d", seconds/60, seconds%60)
}
