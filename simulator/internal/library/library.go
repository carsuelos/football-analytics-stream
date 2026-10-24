// Package library downloads StatsBomb open data into the simulator's data
// directory, so a match can be added from the dashboard instead of with
// scripts/fetch_statsbomb.py. It writes the same layout the catalog reads:
//
//	<dir>/competitions.json
//	<dir>/matches/<competition_id>/<season_id>.json
//	<dir>/events/<match_id>.json
//	<dir>/lineups/<match_id>.json
//
// Files are written to a temporary name and renamed, so the catalog never
// reads half a file, and files already on disk are skipped. One download runs
// at a time, in the background; Get reports its progress.
//
// Data: https://github.com/statsbomb/open-data, free for non-commercial use
// under StatsBomb's terms (attribution required).
package library

import (
	"cmp"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"slices"
	"strconv"
	"sync"
	"time"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
)

// DefaultBaseURL is StatsBomb's open data on GitHub.
const DefaultBaseURL = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"

const (
	// refreshAfter is how long the list of seasons is reused before asking again.
	refreshAfter = time.Hour
	workers      = 8
)

// ErrBusy is returned when a download is already running.
var ErrBusy = errors.New("a download is already running")

// ErrUnknownSeason is returned for a season StatsBomb doesn't list.
var ErrUnknownSeason = errors.New("no such competition season in StatsBomb's open data")

// Library is a data directory and its downloads. Create it with New.
type Library struct {
	Dir     string
	BaseURL string
	HTTP    *http.Client
	Log     *slog.Logger

	mu        sync.Mutex
	seasons   []competition
	fetched   time.Time
	listError string
	download  *schema.LibraryDownload
	done      chan struct{} // closed when the current download ends
}

// competition is one entry of StatsBomb's competitions.json.
type competition struct {
	CompetitionID int    `json:"competition_id"`
	SeasonID      int    `json:"season_id"`
	Competition   string `json:"competition_name"`
	Season        string `json:"season_name"`
	Country       string `json:"country_name"`
	Gender        string `json:"competition_gender"`
	Youth         bool   `json:"competition_youth"`
}

type matchRef struct {
	MatchID int `json:"match_id"`
}

// New returns a library over dir, downloading from StatsBomb's open data.
func New(dir string, log *slog.Logger) *Library {
	return &Library{Dir: dir, BaseURL: DefaultBaseURL, HTTP: &http.Client{Timeout: time.Minute}, Log: log}
}

// Get returns the seasons, newest first, with how many of each are on disk,
// and the download's progress.
func (l *Library) Get(ctx context.Context) schema.MatchLibrary {
	l.refresh(ctx)
	l.mu.Lock()
	seasons := slices.Clone(l.seasons)
	out := schema.MatchLibrary{SchemaVersion: 1, Seasons: []schema.LibrarySeason{}}
	if l.download != nil {
		d := *l.download
		out.Download = &d
	}
	if l.listError != "" {
		e := l.listError
		out.Error = &e
	}
	l.mu.Unlock()
	for _, c := range seasons {
		youth := c.Youth
		s := schema.LibrarySeason{
			CompetitionID: c.CompetitionID,
			SeasonID:      c.SeasonID,
			Competition:   c.Competition,
			Season:        c.Season,
			Gender:        schema.LibrarySeasonGenderMale,
			Youth:         &youth,
		}
		if c.Gender == "female" {
			s.Gender = schema.LibrarySeasonGenderFemale
		}
		if c.Country != "" {
			country := c.Country
			s.Country = &country
		}
		if ids, err := l.matchIDs(c.CompetitionID, c.SeasonID); err == nil {
			n := len(ids)
			s.Matches = &n
			for _, id := range ids {
				if l.exists(eventsPath(id)) {
					s.Downloaded++
				}
			}
		}
		out.Seasons = append(out.Seasons, s)
	}
	return out
}

// refresh reloads the list of seasons from StatsBomb at most every
// refreshAfter, falling back to the copy on disk.
func (l *Library) refresh(ctx context.Context) {
	l.mu.Lock()
	stale := time.Since(l.fetched) > refreshAfter
	l.mu.Unlock()
	if !stale {
		return
	}
	err := l.fetch(ctx, "competitions.json", true)
	var list []competition
	if readErr := readJSON(filepath.Join(l.Dir, "competitions.json"), &list); readErr != nil && err == nil {
		err = readErr
	}
	slices.SortStableFunc(list, func(a, b competition) int {
		return cmp.Or(-cmp.Compare(a.Season, b.Season), cmp.Compare(a.Competition, b.Competition))
	})
	l.mu.Lock()
	defer l.mu.Unlock()
	l.fetched = time.Now()
	l.listError = ""
	if err != nil {
		l.listError = err.Error()
	}
	if len(list) > 0 {
		l.seasons = list
	}
}

// Start downloads a season's matches in the background.
func (l *Library) Start(ctx context.Context, competitionID, seasonID int) (schema.LibraryDownload, error) {
	l.refresh(ctx)
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.download != nil && l.download.State == schema.LibraryDownloadStateDownloading {
		return *l.download, ErrBusy
	}
	i := slices.IndexFunc(l.seasons, func(c competition) bool {
		return c.CompetitionID == competitionID && c.SeasonID == seasonID
	})
	if i < 0 {
		return schema.LibraryDownload{}, ErrUnknownSeason
	}
	c := l.seasons[i]
	l.download = &schema.LibraryDownload{
		CompetitionID: c.CompetitionID,
		SeasonID:      c.SeasonID,
		Competition:   c.Competition,
		Season:        c.Season,
		State:         schema.LibraryDownloadStateDownloading,
	}
	l.done = make(chan struct{})
	go l.run(c, l.done)
	return *l.download, nil
}

// Wait blocks until the current download, if any, ends (for tests).
func (l *Library) Wait() {
	l.mu.Lock()
	done := l.done
	l.mu.Unlock()
	if done != nil {
		<-done
	}
}

func (l *Library) run(c competition, done chan struct{}) {
	defer close(done)
	err := l.season(context.Background(), c)
	l.mu.Lock()
	defer l.mu.Unlock()
	if err != nil {
		msg := err.Error()
		l.download.State, l.download.Error = schema.LibraryDownloadStateFailed, &msg
		if l.Log != nil {
			l.Log.Warn("download failed", "competition", c.Competition, "season", c.Season, "err", err)
		}
		return
	}
	l.download.State = schema.LibraryDownloadStateDone
	if l.Log != nil {
		l.Log.Info("downloaded", "competition", c.Competition, "season", c.Season, "matches", l.download.Total)
	}
}

// season downloads the season's list of matches, then each match's lineups
// and events, a few at a time.
func (l *Library) season(ctx context.Context, c competition) error {
	if err := l.fetch(ctx, matchesPath(c.CompetitionID, c.SeasonID), false); err != nil {
		return err
	}
	ids, err := l.matchIDs(c.CompetitionID, c.SeasonID)
	if err != nil {
		return err
	}
	l.mu.Lock()
	l.download.Total = len(ids)
	l.mu.Unlock()

	jobs := make(chan int)
	errs := make(chan error, len(ids))
	var wg sync.WaitGroup
	for range min(workers, max(1, len(ids))) {
		wg.Go(func() {
			for id := range jobs {
				// Lineups first: the catalog lists a match once its events exist.
				err := l.fetch(ctx, lineupsPath(id), false)
				if err == nil {
					err = l.fetch(ctx, eventsPath(id), false)
				}
				errs <- err
				if err == nil {
					l.mu.Lock()
					l.download.Done++
					l.mu.Unlock()
				}
			}
		})
	}
	for _, id := range ids {
		jobs <- id
	}
	close(jobs)
	wg.Wait()
	close(errs)
	var failed []error
	for err := range errs {
		if err != nil {
			failed = append(failed, err)
		}
	}
	if len(failed) > 0 {
		return fmt.Errorf("%d of %d matches failed; the first: %w", len(failed), len(ids), failed[0])
	}
	return nil
}

func (l *Library) matchIDs(competitionID, seasonID int) ([]int, error) {
	var refs []matchRef
	if err := readJSON(filepath.Join(l.Dir, matchesPath(competitionID, seasonID)), &refs); err != nil {
		return nil, err
	}
	ids := make([]int, len(refs))
	for i, r := range refs {
		ids[i] = r.MatchID
	}
	return ids, nil
}

func (l *Library) exists(rel string) bool {
	_, err := os.Stat(filepath.Join(l.Dir, rel))
	return err == nil
}

// fetch downloads BaseURL/rel to Dir/rel, unless it's there and !force.
func (l *Library) fetch(ctx context.Context, rel string, force bool) error {
	if !force && l.exists(rel) {
		return nil
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, l.BaseURL+"/"+rel, nil)
	if err != nil {
		return err
	}
	resp, err := l.HTTP.Do(req)
	if err != nil {
		return fmt.Errorf("statsbomb: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("statsbomb: %s: %s", rel, resp.Status)
	}
	dest := filepath.Join(l.Dir, rel)
	if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(dest), filepath.Base(dest)+".*.part")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if _, err := io.Copy(tmp, resp.Body); err != nil {
		tmp.Close()
		return fmt.Errorf("statsbomb: %s: %w", rel, err)
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), dest)
}

// Paths are relative, with forward slashes: they're both URL paths and file paths.
func matchesPath(competitionID, seasonID int) string {
	return path.Join("matches", strconv.Itoa(competitionID), strconv.Itoa(seasonID)+".json")
}

func eventsPath(id int) string  { return path.Join("events", strconv.Itoa(id)+".json") }
func lineupsPath(id int) string { return path.Join("lineups", strconv.Itoa(id)+".json") }

func readJSON(file string, v any) error {
	b, err := os.ReadFile(file)
	if err != nil {
		return err
	}
	return json.Unmarshal(b, v)
}
