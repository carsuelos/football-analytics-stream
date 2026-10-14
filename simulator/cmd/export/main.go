// Command export writes matches as the feed broadcasts them, for offline replay.
//
//	export [-data data/statsbomb] [-out data/feeds] [-jitter 3s] [-seed 1] [match_id ...]
//
// For each match (every downloaded one if none are given), <out>/<match_id>.jsonl
// holds the feed messages a subscriber there from the start receives: a
// match_start, every event, then a match_end, one JSON message per line.
// <out>/matches.json lists the exported matches (a MatchList).
//
// The engine replays these files without the simulator, its clock or a
// network (python -m engine.backtest), and gets exactly what it gets live from
// the same broadcast. The conversion from StatsBomb is the simulator's own, so
// there is still only one.
package main

import (
	"bufio"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"sync"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/broadcast"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/jitter"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/match"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/statsbomb"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "export:", err)
		os.Exit(1)
	}
}

func run(args []string) error {
	flags := flag.NewFlagSet("export", flag.ExitOnError)
	dataDir := flags.String("data", "data/statsbomb", "StatsBomb open-data directory (see make fetch-data)")
	out := flags.String("out", "data/feeds", "directory to write the feeds to")
	maxDelay := flags.Duration("jitter", 0, "deliver events up to this much match time late, as the simulator's -jitter")
	seed := flags.Uint64("seed", 1, "random seed for -jitter")
	workers := flags.Int("workers", runtime.NumCPU(), "matches to convert at once")
	flags.Parse(args)
	if *maxDelay < 0 {
		return errors.New("-jitter must not be negative")
	}
	if *workers < 1 {
		return errors.New("-workers must be at least 1")
	}

	catalog := statsbomb.NewCatalog(*dataDir)
	infos, err := catalog.List()
	if err != nil {
		return err
	}
	infos, err = choose(infos, flags.Args())
	if err != nil {
		return err
	}
	if err := os.MkdirAll(*out, 0o755); err != nil {
		return err
	}

	jobs := make(chan match.Info)
	errs := make(chan error, len(infos))
	var wg sync.WaitGroup
	for range *workers {
		wg.Go(func() {
			for info := range jobs {
				errs <- export(catalog, info, *out, maxDelay.Seconds(), *seed)
			}
		})
	}
	for _, info := range infos {
		jobs <- info
	}
	close(jobs)
	wg.Wait()
	close(errs)
	var all []error
	for err := range errs {
		all = append(all, err)
	}
	if err := errors.Join(all...); err != nil {
		return err
	}
	list := schema.MatchList{SchemaVersion: 1, Matches: infos}
	if list.Matches == nil {
		list.Matches = []schema.MatchInfo{}
	}
	if err := writeAtomically(filepath.Join(*out, "matches.json"), func(w *bufio.Writer) error {
		return json.NewEncoder(w).Encode(list)
	}); err != nil {
		return err
	}
	fmt.Fprintf(os.Stderr, "exported %d matches to %s\n", len(infos), *out)
	return nil
}

func export(catalog *statsbomb.Catalog, info match.Info, out string, maxDelay float64, seed uint64) error {
	m, err := catalog.LoadInfo(info)
	if err != nil {
		return err
	}
	if maxDelay > 0 {
		m = jitter.Match(m, maxDelay, seed)
	}
	return writeAtomically(filepath.Join(out, fmt.Sprintf("%d.jsonl", info.MatchID)), func(w *bufio.Writer) error {
		enc := json.NewEncoder(w) // one message per line
		for _, msg := range broadcast.Messages(m) {
			if err := enc.Encode(msg); err != nil {
				return err
			}
		}
		return nil
	})
}

// choose picks the matches with the given ids, in that order, or all of them.
func choose(infos []match.Info, ids []string) ([]match.Info, error) {
	if len(ids) == 0 {
		return infos, nil
	}
	byID := make(map[int]match.Info, len(infos))
	for _, info := range infos {
		byID[int(info.MatchID)] = info
	}
	chosen := make([]match.Info, 0, len(ids))
	for _, s := range ids {
		id, err := strconv.Atoi(s)
		if err != nil {
			return nil, fmt.Errorf("match id %q: %w", s, err)
		}
		info, ok := byID[id]
		if !ok {
			return nil, fmt.Errorf("match %d: %w (run make fetch-data)", id, match.ErrNotFound)
		}
		chosen = append(chosen, info)
	}
	return chosen, nil
}

// writeAtomically writes path through a temporary file, so a reader never sees
// half a file and an interrupted export leaves no broken ones.
func writeAtomically(path string, write func(*bufio.Writer) error) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), filepath.Base(path)+".*.part")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name()) // a no-op once renamed
	w := bufio.NewWriter(tmp)
	if err := errors.Join(write(w), w.Flush(), tmp.Close()); err != nil {
		return fmt.Errorf("%s: %w", path, err)
	}
	return os.Rename(tmp.Name(), path)
}
