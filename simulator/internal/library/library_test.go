package library

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
)

const competitions = `[
 {"competition_id": 43, "season_id": 106, "competition_name": "FIFA World Cup", "season_name": "2022", "country_name": "International", "competition_gender": "male", "competition_youth": false},
 {"competition_id": 53, "season_id": 315, "competition_name": "UEFA Women's Euro", "season_name": "2025", "country_name": "Europe", "competition_gender": "female", "competition_youth": false}
]`

// fake serves StatsBomb's layout: two seasons, the Euro with matches 1 and 2,
// match 2's events failing if broken is set. It counts requests by path.
func fake(t *testing.T, broken *atomic.Bool) (*Library, map[string]*atomic.Int32) {
	t.Helper()
	hits := map[string]*atomic.Int32{}
	for _, p := range []string{"/competitions.json", "/matches/53/315.json", "/events/1.json", "/events/2.json", "/lineups/1.json", "/lineups/2.json"} {
		hits[p] = &atomic.Int32{}
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if n, ok := hits[r.URL.Path]; ok {
			n.Add(1)
		}
		switch {
		case r.URL.Path == "/competitions.json":
			w.Write([]byte(competitions))
		case r.URL.Path == "/matches/53/315.json":
			w.Write([]byte(`[{"match_id": 1}, {"match_id": 2}]`))
		case r.URL.Path == "/events/2.json" && broken != nil && broken.Load():
			http.Error(w, "nope", http.StatusBadGateway)
		case strings.HasPrefix(r.URL.Path, "/events/"), strings.HasPrefix(r.URL.Path, "/lineups/"):
			w.Write([]byte(`[]`))
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(srv.Close)
	l := New(t.TempDir(), nil)
	l.BaseURL, l.HTTP = srv.URL, srv.Client()
	return l, hits
}

func TestItListsTheSeasonsNewestFirst(t *testing.T) {
	l, _ := fake(t, nil)
	lib := l.Get(context.Background())
	if len(lib.Seasons) != 2 || lib.Error != nil || lib.Download != nil {
		t.Fatalf("library %+v", lib)
	}
	euro := lib.Seasons[0]
	if euro.Competition != "UEFA Women's Euro" || euro.Gender != schema.LibrarySeasonGenderFemale ||
		*euro.Country != "Europe" || euro.Downloaded != 0 || euro.Matches != nil {
		t.Errorf("euro %+v", euro)
	}
}

func TestItDownloadsASeasonOnceAndCountsIt(t *testing.T) {
	l, hits := fake(t, nil)
	ctx := context.Background()
	if _, err := l.Start(ctx, 53, 315); err != nil {
		t.Fatal(err)
	}
	l.Wait()
	lib := l.Get(ctx)
	if d := lib.Download; d == nil || d.State != schema.LibraryDownloadStateDone || d.Done != 2 || d.Total != 2 {
		t.Fatalf("download %+v", lib.Download)
	}
	if euro := lib.Seasons[0]; euro.Downloaded != 2 || *euro.Matches != 2 {
		t.Errorf("euro %+v", euro)
	}
	for _, f := range []string{"matches/53/315.json", "events/1.json", "lineups/2.json"} {
		if _, err := os.Stat(filepath.Join(l.Dir, f)); err != nil {
			t.Errorf("%s: %v", f, err)
		}
	}
	if parts, _ := filepath.Glob(filepath.Join(l.Dir, "*", "*.part")); len(parts) > 0 {
		t.Errorf("left %v", parts)
	}
	// Again: nothing new is downloaded.
	if _, err := l.Start(ctx, 53, 315); err != nil {
		t.Fatal(err)
	}
	l.Wait()
	if n := hits["/events/1.json"].Load(); n != 1 {
		t.Errorf("events/1 fetched %d times", n)
	}
}

func TestAFailedMatchFailsTheDownloadAndCanBeRetried(t *testing.T) {
	var broken atomic.Bool
	broken.Store(true)
	l, _ := fake(t, &broken)
	ctx := context.Background()
	l.Start(ctx, 53, 315)
	l.Wait()
	d := l.Get(ctx).Download
	if d.State != schema.LibraryDownloadStateFailed || d.Done != 1 || !strings.Contains(*d.Error, "1 of 2 matches failed") {
		t.Fatalf("download %+v", d)
	}
	broken.Store(false)
	l.Start(ctx, 53, 315)
	l.Wait()
	if d := l.Get(ctx).Download; d.State != schema.LibraryDownloadStateDone || d.Done != 2 {
		t.Errorf("retry %+v", d)
	}
}

func TestOneDownloadAtATimeAndOnlyKnownSeasons(t *testing.T) {
	l, _ := fake(t, nil)
	ctx := context.Background()
	if _, err := l.Start(ctx, 99, 1); !errors.Is(err, ErrUnknownSeason) {
		t.Errorf("unknown season: %v", err)
	}
	l.mu.Lock()
	l.download = &schema.LibraryDownload{State: schema.LibraryDownloadStateDownloading}
	l.mu.Unlock()
	if _, err := l.Start(ctx, 53, 315); !errors.Is(err, ErrBusy) {
		t.Errorf("busy: %v", err)
	}
}

func TestOfflineItKeepsTheListOnDisk(t *testing.T) {
	l, _ := fake(t, nil)
	ctx := context.Background()
	l.Get(ctx)
	l.BaseURL = "http://127.0.0.1:1"
	l.fetched = l.fetched.AddDate(0, 0, -1)
	lib := l.Get(ctx)
	if len(lib.Seasons) != 2 || lib.Error == nil {
		t.Errorf("offline: %d seasons, error %v", len(lib.Seasons), lib.Error)
	}
}

func TestInTrainingIsTheTrainingDataRule(t *testing.T) {
	for _, c := range []struct {
		competition, season, gender string
		youth, want                 bool
	}{
		{"Premier League", "2015/2016", "male", false, true},
		{"UEFA Euro", "2024", "male", false, true},
		{"FIFA World Cup", "2022", "male", false, false}, // the test set
		{"FIFA World Cup", "1970", "male", false, false},
		{"UEFA Women's Euro", "2025", "female", false, false},
		{"FIFA U20 World Cup", "1979", "male", true, false},
	} {
		if got := InTraining(c.competition, c.season, c.gender, c.youth); got != c.want {
			t.Errorf("%s %s: %v", c.competition, c.season, got)
		}
	}
	// The same rule as the script that downloads the training data.
	script, err := os.ReadFile("../../../scripts/fetch_statsbomb.py")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{
		fmt.Sprintf("TRAINING_SINCE = %d", TrainingSince),
		fmt.Sprintf(`"--competition", default=%q`, TestCompetition),
		fmt.Sprintf(`"--season", default=%q`, TestSeason),
		`c["competition_gender"] == "male"`,
		`not c.get("competition_youth")`,
	} {
		if !strings.Contains(string(script), want) {
			t.Errorf("scripts/fetch_statsbomb.py no longer has %s", want)
		}
	}
}
