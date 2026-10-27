// Command livefeed records Sportmonks' live matches to tapes, as they arrive.
//
//	livefeed -record DIR [-interval 3s] [-idle-interval 2m] [-includes ...] [-for 3h]
//	livefeed -record DIR -history FROM:TO
//	livefeed -export OUT -tapes DIR
//	livefeed -summary DIR
//
// With -record it polls the livescores (every match from 15 minutes before
// kick-off to 15 minutes after full time, in one call) and writes what changed
// in each to DIR/<UTC date>/<fixture id>.jsonl; see package tape. It polls
// every -interval while a match is listed and every -idle-interval otherwise,
// but never faster than the hour's calls allow: it spreads what's left of them
// over what's left of the hour (the free plan has 180 an hour, so about one
// every 20 s; Starter 2,000). An include the plan doesn't have is dropped, with
// a warning, rather than stopping the recording. The type catalogue (what each
// type_id means) is saved once, to DIR/types.json.
//
// With -history it fetches, once, every finished fixture on the plan that
// kicked off from FROM to TO (YYYY-MM-DD), each to a one-line tape in
// DIR/history/<UTC date>/.
//
// -export maps every tape in DIR to the canonical feed (see package mapper):
// OUT/<fixture id>.jsonl, as the simulator's export writes them, and
// OUT/matches.json, so python -m engine.backtest OUT replays them.
//
// -summary prints what each tape in DIR holds.
//
// The token comes from SPORTMONKS_API_TOKEN (make livefeed reads it from .env)
// and is only ever sent in a request header.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"io/fs"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"syscall"
	"time"

	"github.com/carsuelos/football-analytics-stream/livefeed/internal/sportmonks"
	"github.com/carsuelos/football-analytics-stream/livefeed/internal/tape"
)

// DefaultIncludes is what each poll asks for. The free plan refuses trends and
// ballCoordinates (they're dropped); pressure and xGFixture are paid add-ons.
const DefaultIncludes = "participants;scores;periods;state;league;season;events;statistics;trends;lineups;ballCoordinates"

// refusedInclude finds the include in the API's "You do not have access to the
// 'trends' include".
var refusedInclude = regexp.MustCompile(`access to the '([^']+)' include`)

func main() {
	if err := run(os.Args[1:], os.Getenv, os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, "livefeed:", err)
		os.Exit(1)
	}
}

func run(args []string, getenv func(string) string, stdout io.Writer) error {
	fl := flag.NewFlagSet("livefeed", flag.ContinueOnError)
	record := fl.String("record", "", "record the live matches to tapes in this directory")
	summary := fl.String("summary", "", "summarize the tapes in this directory")
	history := fl.String("history", "", "with -record: fetch the finished fixtures from one date to another once (FROM:TO, YYYY-MM-DD)")
	export := fl.String("export", "", "map the tapes in -tapes to canonical feeds in this directory")
	tapes := fl.String("tapes", "", "with -export: where the tapes are")
	interval := fl.Duration("interval", 3*time.Second, "how often to poll while a match is listed")
	idle := fl.Duration("idle-interval", 2*time.Minute, "how often to poll while none is")
	includes := fl.String("includes", DefaultIncludes, "what to include with each fixture")
	runFor := fl.Duration("for", 0, "stop after this long (0: until interrupted)")
	baseURL := fl.String("base-url", sportmonks.DefaultBaseURL, "the API's root")
	if err := fl.Parse(args); err != nil {
		return err
	}
	switch {
	case *summary != "":
		return summarize(*summary, stdout)
	case *export != "":
		if *tapes == "" {
			return errors.New("-export needs -tapes DIR")
		}
		return exportFeeds(*tapes, *export, stdout)
	case *record == "":
		return errors.New("say -record DIR, -export OUT -tapes DIR or -summary DIR")
	}
	token := strings.TrimSpace(getenv("SPORTMONKS_API_TOKEN"))
	if token == "" {
		return errors.New("no SPORTMONKS_API_TOKEN (put it in .env and use make livefeed)")
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if *runFor > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, *runFor)
		defer cancel()
	}
	client := sportmonks.New(token, &http.Client{Timeout: 30 * time.Second})
	client.BaseURL = *baseURL
	if *history != "" {
		from, to, ok := strings.Cut(*history, ":")
		if !ok {
			return errors.New("-history is FROM:TO, e.g. 2026-10-01:2026-10-26")
		}
		return fetchHistory(ctx, client, *record, from, to, *includes, stdout)
	}
	r := &recorder{
		client: client, tapes: tape.NewWriter(*record), dir: *record, includes: *includes,
		interval: *interval, idle: *idle, log: slog.Default(), now: time.Now,
	}
	defer r.tapes.Close()
	return r.run(ctx)
}

type recorder struct {
	client         *sportmonks.Client
	tapes          *tape.Writer
	dir, includes  string
	interval, idle time.Duration
	log            *slog.Logger
	now            func() time.Time
}

func (r *recorder) run(ctx context.Context) error {
	r.log.Info("livefeed recording", "dir", r.dir, "interval", r.interval, "idle_interval", r.idle, "includes", r.includes)
	r.saveTypes(ctx)
	var (
		lines, polls int
		lastLog      = r.now()
		failures     int
	)
	for {
		wait, err := r.poll(ctx, &lines)
		polls++
		switch {
		case err == nil:
			failures = 0
		case ctx.Err() != nil:
			return nil
		case sportmonks.RateLimited(err):
			r.log.Warn("out of calls for the hour; waiting", "for", 5*time.Minute)
			wait = 5 * time.Minute
		case r.dropRefused(err):
			wait = 0
		default:
			var apiErr *sportmonks.Error
			if errors.As(err, &apiErr) && apiErr.Status >= 400 && apiErr.Status < 500 {
				// A bad token or an include the plan doesn't have: polling again won't help.
				return err
			}
			failures++
			wait = min(r.interval*time.Duration(1<<min(failures, 5)), time.Minute)
			r.log.Warn("poll failed; retrying", "err", err, "in", wait)
		}
		if r.now().Sub(lastLog) >= time.Minute {
			r.log.Info("recording", "polls", polls, "lines_written", lines)
			lastLog, polls, lines = r.now(), 0, 0
		}
		select {
		case <-ctx.Done():
			r.log.Info("livefeed stopped")
			return nil
		case <-time.After(wait):
		}
	}
}

// poll records one poll and says how long to wait before the next.
func (r *recorder) poll(ctx context.Context, lines *int) (time.Duration, error) {
	fixtures, rl, err := r.client.Livescores(ctx, r.includes)
	if err != nil {
		return 0, err
	}
	n, err := r.tapes.Record(r.now(), fixtures)
	*lines += n
	if err != nil {
		r.log.Warn("recording", "err", err)
	}
	wait := r.interval
	if len(fixtures) == 0 {
		wait = r.idle
	}
	return max(wait, pace(rl)), nil
}

// pace spreads the hour's remaining calls over the rest of the hour.
func pace(rl *sportmonks.RateLimit) time.Duration {
	if rl == nil {
		return 0
	}
	left := time.Duration(rl.ResetsInSeconds) * time.Second
	return left / time.Duration(max(rl.Remaining, 1))
}

// dropRefused drops an include the plan doesn't have, if that's what err says.
func (r *recorder) dropRefused(err error) bool {
	var apiErr *sportmonks.Error
	if !errors.As(err, &apiErr) || apiErr.Status != http.StatusForbidden {
		return false
	}
	m := refusedInclude.FindStringSubmatch(apiErr.Message)
	if m == nil {
		return false
	}
	kept := dropInclude(r.includes, m[1])
	if kept == r.includes {
		return false
	}
	r.includes = kept
	r.log.Warn("the plan doesn't include this; recording without it", "include", m[1], "includes", r.includes)
	return true
}

// saveTypes writes the type catalogue once; a failure only means the tapes
// will have type ids without names until the next run.
func (r *recorder) saveTypes(ctx context.Context) {
	path := filepath.Join(r.dir, "types.json")
	if _, err := os.Stat(path); err == nil {
		return
	}
	types, err := r.client.Types(ctx)
	if err == nil {
		var b []byte
		if b, err = json.MarshalIndent(types, "", " "); err == nil {
			if err = os.MkdirAll(r.dir, 0o755); err == nil {
				err = os.WriteFile(path, b, 0o644)
			}
		}
	}
	if err != nil {
		r.log.Warn("couldn't save the type catalogue", "err", err)
		return
	}
	r.log.Info("saved the type catalogue", "types", len(types), "path", path)
}

func summarize(dir string, out io.Writer) error {
	names := typeNames(filepath.Join(dir, "types.json"))
	var paths []string
	err := filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
		if err == nil && !d.IsDir() && strings.HasSuffix(p, ".jsonl") {
			paths = append(paths, p)
		}
		return err
	})
	if err != nil {
		return err
	}
	sort.Strings(paths)
	if len(paths) == 0 {
		fmt.Fprintln(out, "No tapes in", dir)
	}
	for _, p := range paths {
		s, err := tape.Summarize(p)
		if err != nil {
			fmt.Fprintf(out, "%s: %v\n", p, err)
			continue
		}
		info, _ := os.Stat(p)
		fmt.Fprintf(out, "%s  %s (fixture %d, state %s)\n", strings.TrimPrefix(p, dir+"/"), s.Name, s.FixtureID, s.FinalState)
		fmt.Fprintf(out, "  %s – %s UTC, %d lines (%d keyframes), %.1f MB, longest gap %s\n",
			s.First.Format("Jan 2 15:04:05"), s.Last.Format("15:04:05"), s.Lines, s.Keyframes,
			float64(info.Size())/1e6, s.LongestGap.Round(time.Second))
		var lists []string
		for k, n := range s.Lists {
			lists = append(lists, fmt.Sprintf("%s %d", k, n))
		}
		sort.Strings(lists)
		fmt.Fprintf(out, "  lists: %s\n", strings.Join(lists, ", "))
		var events []string
		for id, n := range s.EventTypes {
			name := names[id]
			if name == "" {
				name = fmt.Sprintf("type %d", id)
			}
			events = append(events, fmt.Sprintf("%s %d", name, n))
		}
		sort.Strings(events)
		fmt.Fprintf(out, "  events: %s; %d removed along the way; the score changed %d times\n",
			strings.Join(events, ", "), s.RemovedEvents, s.ScoreChanges)
		fmt.Fprintf(out, "  fields: %s\n", strings.Join(s.FieldsReceived, ", "))
	}
	return nil
}

// typeNames reads the saved type catalogue: id to name.
func typeNames(path string) map[int]string {
	names := map[int]string{}
	b, err := os.ReadFile(path)
	if err != nil {
		return names
	}
	var types []struct {
		ID   int    `json:"id"`
		Name string `json:"name"`
	}
	if json.Unmarshal(b, &types) == nil {
		for _, t := range types {
			names[t.ID] = t.Name
		}
	}
	return names
}
