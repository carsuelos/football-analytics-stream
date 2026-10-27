package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/carsuelos/football-analytics-stream/livefeed/internal/mapper"
	"github.com/carsuelos/football-analytics-stream/livefeed/internal/schema"
	"github.com/carsuelos/football-analytics-stream/livefeed/internal/sportmonks"
	"github.com/carsuelos/football-analytics-stream/livefeed/internal/tape"
)

// finished are the fixture states of a match that's over.
var finished = map[int]bool{5: true, 7: true, 8: true}

// fetchHistory writes each finished fixture from one date to another to a
// one-line tape, dropping includes the plan refuses.
func fetchHistory(ctx context.Context, c *sportmonks.Client, dir, from, to, includes string, out io.Writer) error {
	var fixtures []json.RawMessage
	for {
		var err error
		fixtures, err = c.FixturesBetween(ctx, from, to, includes)
		if err == nil {
			break
		}
		var apiErr *sportmonks.Error
		m := refusedInclude.FindStringSubmatch(err.Error())
		if !errors.As(err, &apiErr) || m == nil {
			return err
		}
		includes = dropInclude(includes, m[1])
		fmt.Fprintf(out, "The plan doesn't include %s; fetching without it\n", m[1])
	}
	w := tape.NewWriter(filepath.Join(dir, "history"))
	defer w.Close()
	var done []json.RawMessage
	for _, f := range fixtures {
		var s struct {
			StateID int `json:"state_id"`
		}
		if json.Unmarshal(f, &s) == nil && finished[s.StateID] {
			done = append(done, f)
		}
	}
	n, err := w.Record(time.Now(), done)
	fmt.Fprintf(out, "%d fixtures from %s to %s, %d finished: %d tapes in %s\n", len(fixtures), from, to, len(done), n, filepath.Join(dir, "history"))
	return err
}

func dropInclude(includes, refused string) string {
	var kept []string
	for _, inc := range strings.Split(includes, ";") {
		base, _, _ := strings.Cut(inc, ".")
		if !strings.EqualFold(base, refused) {
			kept = append(kept, inc)
		}
	}
	return strings.Join(kept, ";")
}

var tapeName = regexp.MustCompile(`^\d+\.jsonl$`)

// exportFeeds maps every tape in dir to a canonical feed in out.
func exportFeeds(dir, out string, w io.Writer) error {
	var paths []string
	outAbs, _ := filepath.Abs(out)
	err := filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			// The feeds themselves are named like tapes: don't read them back.
			if abs, _ := filepath.Abs(p); abs == outAbs {
				return filepath.SkipDir
			}
			return nil
		}
		if tapeName.MatchString(d.Name()) {
			paths = append(paths, p)
		}
		return nil
	})
	if err != nil {
		return err
	}
	sort.Strings(paths)
	if err := os.MkdirAll(out, 0o755); err != nil {
		return err
	}
	// A fixture can have several tapes (one per day it was live, or a live
	// tape and a history one): the last one written wins.
	infos := map[schema.MatchID]schema.MatchInfo{}
	for _, p := range paths {
		info, events, err := exportOne(p, out)
		if err != nil {
			fmt.Fprintf(w, "%s: %v\n", p, err)
			continue
		}
		if events == 0 {
			continue
		}
		infos[info.MatchID] = info
		fmt.Fprintf(w, "%d %s %d-%d %s: %d events\n", info.MatchID, info.HomeTeam.Name, info.HomeScore, info.AwayScore, info.AwayTeam.Name, events)
	}
	list := schema.MatchList{SchemaVersion: 1, Matches: []schema.MatchInfo{}}
	for _, info := range infos {
		list.Matches = append(list.Matches, info)
	}
	sort.Slice(list.Matches, func(i, j int) bool { return list.Matches[i].MatchID < list.Matches[j].MatchID })
	b, err := json.Marshal(list)
	if err != nil {
		return err
	}
	fmt.Fprintf(w, "%d matches in %s\n", len(list.Matches), out)
	return os.WriteFile(filepath.Join(out, "matches.json"), b, 0o644)
}

func exportOne(path, out string) (schema.MatchInfo, int, error) {
	var (
		m      *mapper.Mapper
		last   json.RawMessage
		lines  []byte
		events int
	)
	err := tape.Read(path, func(s tape.Snapshot) error {
		if m == nil {
			m = mapper.New(int(s.FixtureID))
		}
		msgs, err := m.Next(s.Fixture, s.ReceivedAt)
		if err != nil {
			return err
		}
		for _, msg := range msgs {
			b, err := json.Marshal(msg)
			if err != nil {
				return err
			}
			lines = append(append(lines, b...), '\n')
			if msg.Kind == schema.FeedMessageKindEvent {
				events++
			}
		}
		last = s.Fixture
		return nil
	})
	if err != nil || last == nil {
		return schema.MatchInfo{}, 0, err
	}
	info, err := mapper.Info(last)
	if err != nil || events == 0 {
		return info, events, err
	}
	return info, events, os.WriteFile(filepath.Join(out, fmt.Sprintf("%d.jsonl", info.MatchID)), lines, 0o644)
}
