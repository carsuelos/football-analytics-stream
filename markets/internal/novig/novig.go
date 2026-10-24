// Package novig reads Novig's soccer games: per game, total goals, the
// result (each team to win, and a draw) and each team's goals. Its public catalog serves them
// without a key, throttled per IP, so a league is two requests: its events,
// then all their markets of those types.
//
// Novig lists bids only, on both sides of each market: buying Yes at the ask
// is taking someone's bid for No, so the Yes ask is 1 - the No bid, with the
// No bid's size. Its taker fee is charged only once the game is live
// ("WHEN_LIVE") on game markets. A Novig contract pays 1¢, so its quantities
// are divided by 100 to compare with the other venues' $1 contracts.
package novig

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/carsuelos/football-analytics-stream/markets/internal/schema"
	"github.com/carsuelos/football-analytics-stream/markets/internal/teams"
	"github.com/carsuelos/football-analytics-stream/markets/internal/venue"
)

// DefaultBaseURL is Novig's production API.
const DefaultBaseURL = "https://api.novig.com"

// leagues are Novig's names for ours.
var leagues = map[schema.League]string{
	schema.LeagueEpl:    "EPL",
	schema.LeagueLaliga: "La Liga",
}

const (
	statusPregame = "OPEN_PREGAME"
	statusInGame  = "OPEN_INGAME"
	marketTypes   = "TOTAL,MONEYLINE_3_WAY_WIN,MONEYLINE_3_WAY_DRAW,TEAM_TOTAL"
	// A Novig contract pays 1¢; the other venues' pay $1.
	centsPerDollar = 100
)

// Client reads Novig's public catalog. Set BaseURL and HTTP.
type Client struct {
	BaseURL string
	HTTP    *http.Client
}

func New(httpClient *http.Client) *Client {
	return &Client{BaseURL: DefaultBaseURL, HTTP: httpClient}
}

func (c *Client) Venue() schema.Venue { return schema.VenueNovig }

type page[T any] struct {
	Items []T     `json:"items"`
	Next  *string `json:"next"`
}

type event struct {
	EventID     string `json:"eventId"`
	Description string `json:"description"`
	Status      string `json:"status"`
	StartsTs    int64  `json:"startsTs"`
}

type market struct {
	MarketID    string    `json:"marketId"`
	EventID     string    `json:"eventId"`
	MarketType  string    `json:"marketType"`
	Description string    `json:"description"`
	Strike      flexFloat `json:"strike"`
	Status      string    `json:"status"`
	Fee         struct {
		Coefficient string `json:"coefficient"`
		Charged     string `json:"charged"`
	} `json:"fee"`
	Outcomes []outcome `json:"outcomes"`
}

type outcome struct {
	Name string `json:"name"`
	Bid  *struct {
		Price string  `json:"price"`
		Qty   float64 `json:"qty"`
	} `json:"bid"`
}

// flexFloat reads a number sent as a number or a string.
type flexFloat float64

func (f *flexFloat) UnmarshalJSON(b []byte) error {
	s := strings.Trim(string(b), `"`)
	if s == "" || s == "null" {
		return nil
	}
	v, err := strconv.ParseFloat(s, 64)
	*f = flexFloat(v)
	return err
}

// Events returns the league's games before and during play.
func (c *Client) Events(ctx context.Context, league schema.League) ([]venue.Event, error) {
	name, ok := leagues[league]
	if !ok {
		return nil, fmt.Errorf("novig: no league %q", league)
	}
	status := statusPregame + "," + statusInGame
	events, err := all[event](ctx, c, "/v3/public/catalog/events", url.Values{"league": {name}, "status": {status}})
	if err != nil {
		return nil, err
	}
	markets, err := all[market](ctx, c, "/v3/public/catalog/markets", url.Values{
		"league": {name}, "marketType": {marketTypes}, "eventStatus": {status},
	})
	if err != nil {
		return nil, err
	}
	byEvent := map[string][]market{}
	for _, m := range markets {
		byEvent[m.EventID] = append(byEvent[m.EventID], m)
	}
	var out []venue.Event
	for _, e := range events {
		if e.Status != statusPregame && e.Status != statusInGame {
			continue
		}
		// "Tottenham Hotspur FC @ Chelsea FC": away @ home.
		a, h, ok := strings.Cut(e.Description, " @ ")
		if !ok {
			continue
		}
		ev := venue.Event{
			Venue:   schema.VenueNovig,
			League:  league,
			EventID: e.EventID,
			Home:    venue.Team{Name: strings.TrimSpace(h)},
			Away:    venue.Team{Name: strings.TrimSpace(a)},
			Kickoff: time.UnixMilli(e.StartsTs).UTC(),
			State:   schema.GameStateScheduled,
		}
		live := e.Status == statusInGame
		if live {
			ev.State = schema.GameStateLive
		}
		for _, m := range byEvent[e.EventID] {
			if q, ok := quote(m, ev, live); ok {
				ev.Quotes = append(ev.Quotes, q)
			}
		}
		out = append(out, ev)
	}
	return out, nil
}

func all[T any](ctx context.Context, c *Client, path string, q url.Values) ([]T, error) {
	var items []T
	q.Set("limit", "1000")
	for range 10 {
		var p page[T]
		if err := venue.GetJSON(ctx, c.HTTP, c.BaseURL+path+"?"+q.Encode(), &p); err != nil {
			return nil, fmt.Errorf("novig: %w", err)
		}
		items = append(items, p.Items...)
		if p.Next == nil || *p.Next == "" || len(p.Items) == 0 {
			break
		}
		q.Set("after", *p.Next)
	}
	return items, nil
}

// quote reads one market's Yes side: Over for a total, Yes for a result.
func quote(m market, ev venue.Event, live bool) (venue.Quote, bool) {
	if m.Status != "OPEN" {
		return venue.Quote{}, false
	}
	coef, _ := strconv.ParseFloat(m.Fee.Coefficient, 64)
	q := venue.Quote{
		MarketID:       m.MarketID,
		FeeCoefficient: coef,
		FeeCharged:     m.Fee.Charged == "ALWAYS" || (m.Fee.Charged == "WHEN_LIVE" && live),
	}
	yes, no := "Yes", "No"
	switch m.MarketType {
	case "TOTAL":
		line := float64(m.Strike)
		q.Kind, q.Outcome, q.Line = schema.ContractKindTotal, schema.OutcomeOver, line
		yes, no = fmt.Sprintf("Over %g", line), fmt.Sprintf("Under %g", line)
	case "TEAM_TOTAL":
		// "Chelsea FC 1.5 TEAM_TOTAL": the team it's for, and the line.
		line := float64(m.Strike)
		desc := strings.TrimSuffix(m.Description, " "+m.MarketType)
		team := strings.TrimSpace(desc[:max(0, strings.LastIndex(desc, " "))])
		q.Kind, q.Line = schema.ContractKindTeamTotal, line
		switch {
		case team == ev.Home.Name || teams.Same(team, ev.Home.Name):
			q.Outcome = schema.OutcomeHome
		case team == ev.Away.Name || teams.Same(team, ev.Away.Name):
			q.Outcome = schema.OutcomeAway
		default:
			return q, false
		}
		yes, no = fmt.Sprintf("Over %g", line), fmt.Sprintf("Under %g", line)
	case "MONEYLINE_3_WAY_DRAW":
		q.Kind, q.Outcome = schema.ContractKindResult, schema.OutcomeDraw
	case "MONEYLINE_3_WAY_WIN":
		// "Chelsea MONEYLINE_3_WAY_WIN": the team it's for.
		team := strings.TrimSpace(strings.TrimSuffix(m.Description, m.MarketType))
		q.Kind = schema.ContractKindResult
		switch {
		case strings.HasPrefix(ev.Home.Name, team):
			q.Outcome = schema.OutcomeHome
		case strings.HasPrefix(ev.Away.Name, team):
			q.Outcome = schema.OutcomeAway
		default:
			return q, false
		}
	default:
		return q, false
	}
	for _, o := range m.Outcomes {
		if o.Bid == nil {
			continue
		}
		p := venue.Dollars(o.Bid.Price)
		if p == nil {
			continue
		}
		switch o.Name {
		case yes:
			q.Bid = venue.Price(*p)
		case no:
			q.Ask = venue.Price(1 - *p)
			size := o.Bid.Qty / centsPerDollar
			q.AskSize = &size
		}
	}
	return q, true
}
