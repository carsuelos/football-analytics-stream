package schema

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// Contract tests: the shared fixtures in schema/fixtures must decode into the
// generated Go types (valid) or be rejected by them (invalid).

const fixturesDir = "../../../schema/fixtures"

func newTarget(t *testing.T, kind string) any {
	t.Helper()
	switch kind {
	case "alert":
		return &Alert{}
	case "command":
		return &PlaybackCommand{}
	case "event":
		return &MatchEvent{}
	case "feed":
		return &FeedMessage{}
	case "match_list":
		return &MatchList{}
	case "metric":
		return &MetricSnapshot{}
	case "status":
		return &PlaybackStatus{}
	}
	t.Fatalf("no Go type registered for fixture kind %q", kind)
	return nil
}

func fixturePaths(t *testing.T, set string) []string {
	t.Helper()
	paths, err := filepath.Glob(filepath.Join(fixturesDir, set, "*", "*.json"))
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) == 0 {
		t.Fatalf("no %s fixtures found under %s", set, fixturesDir)
	}
	return paths
}

func fixtureName(path string) (kind, name string) {
	return filepath.Base(filepath.Dir(path)), filepath.Base(path)
}

func TestValidFixturesRoundTrip(t *testing.T) {
	for _, path := range fixturePaths(t, "valid") {
		kind, name := fixtureName(path)
		t.Run(kind+"/"+name, func(t *testing.T) {
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			target := newTarget(t, kind)
			if err := json.Unmarshal(raw, target); err != nil {
				t.Fatalf("unmarshal: %v", err)
			}
			out, err := json.Marshal(target)
			if err != nil {
				t.Fatalf("marshal: %v", err)
			}
			var want, got any
			if err := json.Unmarshal(raw, &want); err != nil {
				t.Fatal(err)
			}
			if err := json.Unmarshal(out, &got); err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(want, got) {
				t.Errorf("round trip mismatch\nwant: %s\n got: %s", raw, out)
			}
		})
	}
}

func TestInvalidFixturesRejected(t *testing.T) {
	for _, path := range fixturePaths(t, "invalid") {
		kind, name := fixtureName(path)
		t.Run(kind+"/"+name, func(t *testing.T) {
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			if err := json.Unmarshal(raw, newTarget(t, kind)); err == nil {
				t.Errorf("expected %s to be rejected", path)
			}
		})
	}
}
