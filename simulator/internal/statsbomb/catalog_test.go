package statsbomb

import (
	"errors"
	"testing"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/match"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
)

func TestCatalogListOnlyDownloadedMatches(t *testing.T) {
	infos, err := NewCatalog("testdata").List()
	if err != nil {
		t.Fatal(err)
	}
	if len(infos) != 1 {
		t.Fatalf("got %d matches, want 1 (match 200 has no events file): %+v", len(infos), infos)
	}
	got := infos[0]
	if got.MatchID != 100 || got.Competition != "Test Cup" || got.Season != "2030" || got.Stage != "Final" ||
		got.Date != "2030-07-14" || got.HomeScore != 1 || got.AwayScore != 0 {
		t.Errorf("unexpected info: %+v", got)
	}
	if got.HomeTeam != (schema.Team{ID: 1, Name: "Home FC"}) || got.AwayTeam != (schema.Team{ID: 2, Name: "Away FC"}) {
		t.Errorf("unexpected teams: %+v / %+v", got.HomeTeam, got.AwayTeam)
	}
}

func TestCatalogLoad(t *testing.T) {
	m, err := NewCatalog("testdata").Load(100)
	if err != nil {
		t.Fatal(err)
	}
	if m.MatchID != 100 || m.HomeTeam.Name != "Home FC" {
		t.Errorf("unexpected info: %+v", m.Info)
	}
	wantIDs := []string{"e1-half-start", "e2-xi", "e3-pass", "e4-receipt", "e5-shot"}
	if len(m.Events) != len(wantIDs) {
		t.Fatalf("got %d events, want %d", len(m.Events), len(wantIDs))
	}
	for i, ev := range m.Events {
		if ev.ID != wantIDs[i] || int(ev.Offset) != i {
			t.Errorf("event %d = %s (offset %d), want %s", i, ev.ID, ev.Offset, wantIDs[i])
		}
		assertSchemaValid(t, ev)
	}
	shot := m.Events[4]
	if shot.Period != 2 || shot.MatchClockS != 2700+723.25 || shot.Shot == nil || shot.Shot.Outcome != schema.MatchEventShotOutcomeGoal {
		t.Errorf("unexpected shot: %+v", shot)
	}
}

func TestCatalogLoadUnknownMatch(t *testing.T) {
	for _, id := range []int{999, 200} { // 200 is listed upstream but not downloaded
		_, err := NewCatalog("testdata").Load(id)
		if !errors.Is(err, match.ErrNotFound) {
			t.Errorf("Load(%d) error = %v, want match.ErrNotFound", id, err)
		}
	}
}

func TestCatalogMissingDirectory(t *testing.T) {
	infos, err := NewCatalog("testdata/does-not-exist").List()
	if err != nil || len(infos) != 0 {
		t.Errorf("List on empty dir = %v, %v; want no matches and no error", infos, err)
	}
}
