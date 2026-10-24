// Package venue is what the markets service needs from a prediction market:
// a league's games, as the venue lists them, with its prices for the contracts
// we compare (total goals and the result, both settled on regulation time).
//
// Each venue (packages kalshi, polymarket, novig) turns its own API into these
// types; package board matches the same game across venues and compares them.
package venue

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/carsuelos/football-analytics-stream/markets/internal/schema"
)

// Source is a venue's catalog for a league.
type Source interface {
	Venue() schema.Venue
	// Events returns the league's open games, as the venue lists them now.
	Events(ctx context.Context, league schema.League) ([]Event, error)
}

// Team is how a venue names a team.
type Team struct {
	Name         string
	Abbreviation string // e.g. CFC, if the venue gives one
	Color        string // #rrggbb, if the venue gives one
}

// Event is one game on one venue.
type Event struct {
	Venue   schema.Venue
	League  schema.League
	EventID string
	URL     string

	Home, Away Team
	Kickoff    time.Time
	// KickoffEstimated is set when the venue gives no kick-off time and
	// Kickoff was worked out from its markets (Kalshi).
	KickoffEstimated bool

	// State is "" when the venue doesn't say.
	State schema.GameState
	Score *schema.MarketScore
	Clock string

	Quotes []Quote
}

// Quote is a venue's price to buy Yes on one contract. Prices are dollars a
// contract that pays $1.
type Quote struct {
	Kind    schema.ContractKind
	Outcome schema.Outcome
	Line    float64 // for ContractKindTotal

	MarketID string
	URL      string

	Bid, Ask *float64
	AskSize  *float64 // contracts at the ask

	// FeeCoefficient is the venue's taker fee schedule: a fill at price p
	// costs FeeCoefficient * p * (1 - p) a contract, when FeeCharged.
	FeeCoefficient float64
	FeeCharged     bool
}

// Fee is the taker fee a contract at price p, by the quote's schedule.
func (q Quote) Fee(p float64) float64 {
	if !q.FeeCharged {
		return 0
	}
	return q.FeeCoefficient * p * (1 - p)
}

// Price returns p as a price if it is one a buyer could pay: strictly
// between 0 and 1. A venue shows 0 or 1 when nobody is offering.
func Price(p float64) *float64 {
	if p <= 0 || p >= 1 {
		return nil
	}
	return &p
}

// GetJSON GETs url and decodes the JSON reply into v. A reply other than 2xx
// is an error with its status and the start of its body.
func GetJSON(ctx context.Context, client *http.Client, url string, v any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/json")
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 200))
		return fmt.Errorf("%s: %s %s", req.URL.Path, resp.Status, strings.TrimSpace(string(body)))
	}
	return json.NewDecoder(resp.Body).Decode(v)
}

// Dollars parses a venue's price or quantity string ("0.7500"), or returns nil.
func Dollars(s string) *float64 {
	f, err := strconv.ParseFloat(strings.TrimSpace(s), 64)
	if err != nil {
		return nil
	}
	return &f
}
