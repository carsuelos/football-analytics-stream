package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/match"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
)

const (
	dataDir = "../../../data/statsbomb"
	final   = "3869685"
)

func needFinal(t *testing.T) {
	t.Helper()
	if _, err := os.Stat(filepath.Join(dataDir, "events", final+".json")); err != nil {
		t.Skip("World Cup final not downloaded; run: make fetch-data")
	}
}

func readFeed(t *testing.T, path string) []schema.FeedMessage {
	t.Helper()
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	var msgs []schema.FeedMessage
	sc := bufio.NewScanner(f)
	sc.Buffer(nil, 1<<20)
	for sc.Scan() {
		var msg schema.FeedMessage
		if err := json.Unmarshal(sc.Bytes(), &msg); err != nil { // enforces the schema
			t.Fatalf("line %d: %v", len(msgs)+1, err)
		}
		msgs = append(msgs, msg)
	}
	if err := sc.Err(); err != nil {
		t.Fatal(err)
	}
	return msgs
}

func TestExportsTheFinal(t *testing.T) {
	needFinal(t)
	out := t.TempDir()
	if err := run([]string{"-data", dataDir, "-out", out, final}); err != nil {
		t.Fatal(err)
	}
	msgs := readFeed(t, filepath.Join(out, final+".jsonl"))
	if len(msgs) != 4407+2 {
		t.Fatalf("got %d messages, want 4409", len(msgs))
	}
	first, last := msgs[0], msgs[len(msgs)-1]
	if first.Kind != schema.FeedMessageKindMatchStart || *first.Marker.Head != 0 {
		t.Errorf("first message: %+v", first)
	}
	if last.Kind != schema.FeedMessageKindMatchEnd || last.Marker.Offset != 4407 {
		t.Errorf("last message: %+v", last)
	}

	data, err := os.ReadFile(filepath.Join(out, "matches.json"))
	if err != nil {
		t.Fatal(err)
	}
	var list schema.MatchList
	if err := json.Unmarshal(data, &list); err != nil {
		t.Fatal(err)
	}
	if len(list.Matches) != 1 || list.Matches[0].MatchID != 3869685 {
		t.Errorf("matches.json: %+v", list.Matches)
	}
	if left, _ := filepath.Glob(filepath.Join(out, "*.part")); len(left) > 0 {
		t.Errorf("temporary files left: %v", left)
	}
}

func TestJitterIsRepeatable(t *testing.T) {
	needFinal(t)
	export := func(args ...string) []byte {
		out := t.TempDir()
		if err := run(append([]string{"-data", dataDir, "-out", out}, append(args, final)...)); err != nil {
			t.Fatal(err)
		}
		data, err := os.ReadFile(filepath.Join(out, final+".jsonl"))
		if err != nil {
			t.Fatal(err)
		}
		return data
	}
	plain := export()
	a := export("-jitter", "3s", "-seed", "7")
	b := export("-jitter", "3s", "-seed", "7")
	if !bytes.Equal(a, b) {
		t.Error("the same seed exported different feeds")
	}
	if bytes.Equal(a, plain) {
		t.Error("-jitter did not change the feed")
	}
}

func TestChoose(t *testing.T) {
	infos := []match.Info{{MatchID: 1}, {MatchID: 2}, {MatchID: 3}}
	got, err := choose(infos, []string{"3", "1"})
	if err != nil || len(got) != 2 || got[0].MatchID != 3 || got[1].MatchID != 1 {
		t.Errorf("choose(3, 1) = %v, %v", got, err)
	}
	if got, _ := choose(infos, nil); len(got) != 3 {
		t.Errorf("choose() = %v, want all", got)
	}
	if _, err := choose(infos, []string{"9"}); !errors.Is(err, match.ErrNotFound) {
		t.Errorf("choose(9) error = %v", err)
	}
	if _, err := choose(infos, []string{"x"}); err == nil {
		t.Error("choose(x) did not fail")
	}
}
