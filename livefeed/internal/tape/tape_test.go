package tape

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

var t0 = time.Date(2026, 10, 31, 15, 0, 0, 0, time.UTC)

// match builds a fixture as Sportmonks sends it.
func match(id int, state int, home, away int, events []string, balls int) json.RawMessage {
	evs := make([]map[string]any, len(events))
	for i, e := range events {
		evs[i] = map[string]any{"id": 1000 + i, "type_id": 14, "info": e}
	}
	coords := make([]map[string]any, balls)
	for i := range coords {
		coords[i] = map[string]any{"id": 5000 + i, "timer": fmt.Sprintf("%02d:%02d", i/6, i%6*10), "x": "0.5", "y": "0.5"}
	}
	b, _ := json.Marshal(map[string]any{
		"id": id, "name": "Celtic vs Rangers", "state_id": state,
		"scores":          []map[string]any{{"id": 1, "participant_id": 53, "score": map[string]int{"goals": home}}, {"id": 2, "participant_id": 62, "score": map[string]int{"goals": away}}},
		"events":          evs,
		"ballcoordinates": coords,
	})
	return b
}

// canon makes two JSON documents comparable regardless of key order.
func canon(t *testing.T, b []byte) any {
	t.Helper()
	var v any
	if err := json.Unmarshal(b, &v); err != nil {
		t.Fatal(err)
	}
	return v
}

func record(t *testing.T, w *Writer, polls [][]json.RawMessage, every time.Duration) {
	t.Helper()
	for i, p := range polls {
		if _, err := w.Record(t0.Add(time.Duration(i)*every), p); err != nil {
			t.Fatal(err)
		}
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
}

func readAll(t *testing.T, path string) []Snapshot {
	t.Helper()
	var out []Snapshot
	if err := Read(path, func(s Snapshot) error { out = append(out, s); return nil }); err != nil {
		t.Fatal(err)
	}
	return out
}

func TestReplayGivesBackEachPollAsReceived(t *testing.T) {
	// Kick-off, ball positions arrive, a goal, a second goal, the second ruled
	// out by VAR, full time (the ball positions list disappears).
	withoutBalls := func(raw json.RawMessage) json.RawMessage {
		var m map[string]json.RawMessage
		_ = json.Unmarshal(raw, &m)
		delete(m, "ballcoordinates")
		m["state_id"] = json.RawMessage("5")
		b, _ := json.Marshal(m)
		return b
	}
	polls := []json.RawMessage{
		match(7, 1, 0, 0, nil, 0),
		match(7, 2, 0, 0, nil, 3),
		match(7, 2, 0, 0, nil, 8),
		match(7, 2, 1, 0, []string{"goal"}, 12),
		match(7, 2, 2, 0, []string{"goal", "goal 2"}, 15),
		match(7, 2, 1, 0, []string{"goal"}, 18),
		withoutBalls(match(7, 5, 1, 0, []string{"goal"}, 18)),
	}
	dir := t.TempDir()
	w := NewWriter(dir)
	var asPolls [][]json.RawMessage
	for _, p := range polls {
		asPolls = append(asPolls, []json.RawMessage{p})
	}
	record(t, w, asPolls, 3*time.Second)

	got := readAll(t, filepath.Join(dir, "2026-10-31", "7.jsonl"))
	if len(got) != len(polls) {
		t.Fatalf("%d snapshots, want %d", len(got), len(polls))
	}
	for i, s := range got {
		if !reflect.DeepEqual(canon(t, s.Fixture), canon(t, polls[i])) {
			t.Errorf("snapshot %d:\n got %s\nwant %s", i, s.Fixture, polls[i])
		}
		if want := t0.Add(time.Duration(i) * 3 * time.Second); !s.ReceivedAt.Equal(want) || s.FixtureID != 7 {
			t.Errorf("snapshot %d at %v fixture %d", i, s.ReceivedAt, s.FixtureID)
		}
	}
	if got[0].Line.Keyframe == nil || got[1].Line.Keyframe != nil {
		t.Errorf("the first line should be the only keyframe")
	}
	// The ruled-out goal is a removal, not a rewrite of the list.
	if r := got[5].Line.Remove["events"]; len(r) != 1 || string(r[0]) != "1001" {
		t.Errorf("remove = %s", got[5].Line.Remove)
	}
	if u := got[3].Line.Upsert["ballcoordinates"]; len(u) != 4 {
		t.Errorf("upserted %d ball positions, want the 4 new ones", len(u))
	}
}

func TestAnUnchangedFixtureWritesNothing(t *testing.T) {
	dir := t.TempDir()
	w := NewWriter(dir)
	p := []json.RawMessage{match(7, 2, 0, 0, nil, 3)}
	for i := range 3 {
		n, err := w.Record(t0.Add(time.Duration(i)*time.Second), p)
		if err != nil {
			t.Fatal(err)
		}
		if want := map[int]int{0: 1}[i]; n != want {
			t.Errorf("poll %d wrote %d lines, want %d", i, n, want)
		}
	}
	_ = w.Close()
}

func TestAKeyframeEveryFewMinutesAndWhenAFixtureComesBack(t *testing.T) {
	dir := t.TempDir()
	w := NewWriter(dir)
	w.KeyframeEvery = time.Minute
	a, b := match(7, 2, 0, 0, nil, 1), match(8, 2, 0, 0, nil, 1)
	steps := []struct {
		at       time.Duration
		fixtures []json.RawMessage
	}{
		{0, []json.RawMessage{a, b}},
		{30 * time.Second, []json.RawMessage{match(7, 2, 0, 0, nil, 2), match(8, 2, 0, 0, nil, 2)}},
		{61 * time.Second, []json.RawMessage{match(7, 2, 0, 0, nil, 3)}}, // 8 left the livescores
		{70 * time.Second, []json.RawMessage{match(7, 2, 0, 0, nil, 4), match(8, 2, 0, 0, nil, 2)}},
	}
	for _, s := range steps {
		if _, err := w.Record(t0.Add(s.at), s.fixtures); err != nil {
			t.Fatal(err)
		}
	}
	_ = w.Close()
	keyframes := func(id int) []bool {
		var k []bool
		for _, s := range readAll(t, filepath.Join(dir, "2026-10-31", fmt.Sprintf("%d.jsonl", id))) {
			k = append(k, s.Line.Keyframe != nil)
		}
		return k
	}
	if got, want := keyframes(7), []bool{true, false, true, false}; !reflect.DeepEqual(got, want) {
		t.Errorf("fixture 7 keyframes %v, want %v", got, want)
	}
	if got, want := keyframes(8), []bool{true, false, true}; !reflect.DeepEqual(got, want) {
		t.Errorf("fixture 8 keyframes %v, want %v", got, want)
	}
}

func TestChangesAreMuchSmallerThanTheFixture(t *testing.T) {
	dir := t.TempDir()
	w := NewWriter(dir)
	var polls [][]json.RawMessage
	for i := range 60 {
		polls = append(polls, []json.RawMessage{match(7, 2, 0, 0, nil, 300+i)})
	}
	record(t, w, polls, 3*time.Second)
	data, err := os.ReadFile(filepath.Join(dir, "2026-10-31", "7.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(string(data)), "\n")
	if len(lines) != 60 {
		t.Fatalf("%d lines", len(lines))
	}
	if first, later := len(lines[0]), len(lines[30]); later*20 > first {
		t.Errorf("a change line is %d bytes against a keyframe's %d", later, first)
	}
}

func TestReadSkipsToTheFirstKeyframe(t *testing.T) {
	path := filepath.Join(t.TempDir(), "7.jsonl")
	content := `{"received_at":"2026-10-31T15:00:00Z","fixture_id":7,"set":{"state_id":2}}
{"received_at":"2026-10-31T15:00:03Z","fixture_id":7,"keyframe":{"id":7,"state_id":2}}
`
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	got := readAll(t, path)
	if len(got) != 1 || !reflect.DeepEqual(canon(t, got[0].Fixture), canon(t, []byte(`{"id":7,"state_id":2}`))) {
		t.Errorf("got %+v", got)
	}
}
