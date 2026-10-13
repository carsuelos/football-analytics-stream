package schema

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// Contract tests: the shared alert fixtures in schema/fixtures must decode
// into the generated Alert (valid) or be rejected by it (invalid).

func fixtures(t *testing.T, set string) []string {
	t.Helper()
	paths, err := filepath.Glob(filepath.Join("../../../schema/fixtures", set, "alert", "*.json"))
	if err != nil {
		t.Fatal(err)
	}
	if set == "valid" && len(paths) == 0 {
		t.Fatal("no valid alert fixtures")
	}
	return paths
}

func TestAlertFixtures(t *testing.T) {
	for _, set := range []string{"valid", "invalid"} {
		for _, path := range fixtures(t, set) {
			t.Run(set+"/"+filepath.Base(path), func(t *testing.T) {
				raw, err := os.ReadFile(path)
				if err != nil {
					t.Fatal(err)
				}
				err = json.Unmarshal(raw, &Alert{})
				if (err == nil) != (set == "valid") {
					t.Errorf("unmarshal: %v", err)
				}
			})
		}
	}
}
