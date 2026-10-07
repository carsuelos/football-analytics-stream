// Package statsbomb reads StatsBomb open data from disk and converts it into the
// provider-neutral match model.
//
// The directory layout is the one written by scripts/fetch_statsbomb.py, which
// mirrors the upstream repository:
//
//	<dir>/matches/<competition_id>/<season_id>.json
//	<dir>/events/<match_id>.json
package statsbomb

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/match"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
)

// Catalog implements match.Catalog over a local StatsBomb data directory.
type Catalog struct {
	dir string
}

// Compile-time check that *Catalog satisfies the interface.
var _ match.Catalog = (*Catalog)(nil)

// NewCatalog returns a catalog rooted at dir (for example data/statsbomb).
func NewCatalog(dir string) *Catalog {
	return &Catalog{dir: dir}
}

// List returns every match whose events file has been downloaded, sorted by
// date and then id.
func (c *Catalog) List() ([]match.Info, error) {
	files, err := filepath.Glob(filepath.Join(c.dir, "matches", "*", "*.json"))
	if err != nil {
		return nil, err
	}
	var infos []match.Info
	for _, f := range files {
		var raws []rawMatch
		if err := readJSON(f, &raws); err != nil {
			return nil, err
		}
		for _, r := range raws {
			if _, err := os.Stat(c.eventsPath(r.MatchID)); err != nil {
				continue // listed upstream but not downloaded
			}
			infos = append(infos, toInfo(r))
		}
	}
	sort.Slice(infos, func(i, j int) bool {
		if infos[i].Date != infos[j].Date {
			return infos[i].Date < infos[j].Date
		}
		return infos[i].ID < infos[j].ID
	})
	return infos, nil
}

// Load reads and normalizes one match.
func (c *Catalog) Load(id int) (*match.Match, error) {
	infos, err := c.List()
	if err != nil {
		return nil, err
	}
	idx := -1
	for i := range infos {
		if infos[i].ID == id {
			idx = i
			break
		}
	}
	if idx < 0 {
		return nil, fmt.Errorf("match %d: %w", id, match.ErrNotFound)
	}

	var raws []rawEvent
	if err := readJSON(c.eventsPath(id), &raws); err != nil {
		return nil, err
	}
	events, err := Normalize(id, raws)
	if err != nil {
		return nil, fmt.Errorf("match %d: %w", id, err)
	}
	return &match.Match{Info: infos[idx], Events: events}, nil
}

func (c *Catalog) eventsPath(id int) string {
	return filepath.Join(c.dir, "events", fmt.Sprintf("%d.json", id))
}

func toInfo(r rawMatch) match.Info {
	return match.Info{
		ID:          r.MatchID,
		Competition: r.Competition.Name,
		Season:      r.Season.Name,
		Stage:       r.Stage.Name,
		Date:        r.MatchDate,
		Home:        schema.Team{ID: r.HomeTeam.ID, Name: r.HomeTeam.Name},
		Away:        schema.Team{ID: r.AwayTeam.ID, Name: r.AwayTeam.Name},
		HomeScore:   r.HomeScore,
		AwayScore:   r.AwayScore,
	}
}

func readJSON(path string, v any) error {
	data, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return fmt.Errorf("%s not found (run `make fetch-data`): %w", path, err)
		}
		return err
	}
	if err := json.Unmarshal(data, v); err != nil {
		return fmt.Errorf("decode %s: %w", path, err)
	}
	return nil
}
