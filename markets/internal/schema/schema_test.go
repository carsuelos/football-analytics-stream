package schema

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// Contract tests: the shared fixtures in schema/fixtures must decode into the
// generated types (valid) or be rejected by them (invalid).
func TestFixtures(t *testing.T) {
	for kind, newValue := range map[string]func() any{
		"market_board":  func() any { return &MarketBoard{} },
		"price_history": func() any { return &PriceHistory{} },
	} {
		for _, set := range []string{"valid", "invalid"} {
			paths, err := filepath.Glob(filepath.Join("../../../schema/fixtures", set, kind, "*.json"))
			if err != nil || len(paths) == 0 {
				t.Fatalf("no %s %s fixtures: %v", set, kind, err)
			}
			for _, path := range paths {
				t.Run(set+"/"+kind+"/"+filepath.Base(path), func(t *testing.T) {
					raw, err := os.ReadFile(path)
					if err != nil {
						t.Fatal(err)
					}
					err = json.Unmarshal(raw, newValue())
					if (err == nil) != (set == "valid") {
						t.Errorf("unmarshal: %v", err)
					}
				})
			}
		}
	}
}
