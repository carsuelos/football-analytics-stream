// Package match defines the provider-neutral match model the simulator replays.
//
// Data providers (today only StatsBomb, see package statsbomb) convert their own
// formats into these types, so playback and the network layer never depend on a
// provider. Swapping in a live feed later means writing another Catalog.
package match

import "github.com/carsuelos/football-analytics-stream/simulator/internal/schema"

// Info describes a match without its events. It is cheap to list.
type Info struct {
	ID          int         `json:"match_id"`
	Competition string      `json:"competition"`
	Season      string      `json:"season"`
	Stage       string      `json:"stage"`
	Date        string      `json:"date"`
	Home        schema.Team `json:"home_team"`
	Away        schema.Team `json:"away_team"`
	HomeScore   int         `json:"home_score"`
	AwayScore   int         `json:"away_score"`
}

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
