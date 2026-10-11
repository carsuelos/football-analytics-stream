// Package match defines the provider-neutral match model the simulator replays.
//
// Data providers (today only StatsBomb, see package statsbomb) convert their own
// formats into these types, so playback and the network layer never depend on a
// provider. Swapping in a live feed later means writing another Catalog.
package match

import (
	"errors"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
)

// ErrNotFound is returned, wrapped, by Catalog.Load for an unknown match id.
// Check for it with errors.Is.
var ErrNotFound = errors.New("match not found")

// Info describes a match without its events. It is cheap to list.
//
// It is an alias of the generated wire type, so GET /matches serves exactly
// what match_list.schema.json describes.
type Info = schema.MatchInfo

// Match is a fully loaded match, ready to replay.
type Match struct {
	Info
	// Events are in feed order: Events[i].Offset == i.
	Events []schema.MatchEvent
}

// Catalog lists and loads matches from some data provider.
type Catalog interface {
	List() ([]Info, error)
	Load(id int) (*Match, error)
}
