// Package polymarket reads Polymarket US's soccer games: each game's result
// (each team to win, and a draw), total goals and each team's goals, all
// after regulation time, and the live score and clock, which Polymarket's
// sports data reports. Reading needs no key.
//
// The league's listing has each game's result markets only. The totals are
// fetched by slug, which Polymarket builds from the game's:
// tsc-epl-cry-new-2026-10-25-2pt5 is over 2.5 goals in that game, and
// tsc-epl-cry-new-2026-10-25-ttg-new-1pt5 Newcastle over 1.5. A league is a
// few requests: its listing, then batches of those slugs.
package polymarket

import (
	"context"
	"fmt"
	"maps"
	"net/http"
	"net/url"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/carsuelos/football-analytics-stream/markets/internal/schema"
	"github.com/carsuelos/football-analytics-stream/markets/internal/venue"
)

// DefaultBaseURL is Polymarket US's public gateway.
const DefaultBaseURL = "https://gateway.polymarket.us"

// leagues are Polymarket's slugs for ours.
var leagues = map[schema.League]string{
	schema.LeagueEpl:        "epl",
	schema.LeagueLaliga:     "lal",
	schema.LeagueBundesliga: "bun",
	schema.LeagueMls:        "mls",
	schema.LeagueUcl:        "ucl",
}

// Client reads Polymarket US. Set BaseURL and HTTP.
type Client struct {
	BaseURL string
	HTTP    *http.Client
}

func New(httpClient *http.Client) *Client {
	return &Client{BaseURL: DefaultBaseURL, HTTP: httpClient}
}

func (c *Client) Venue() schema.Venue { return schema.VenuePolymarket }

type eventsReply struct {
	Events []event `json:"events"`
}

type event struct {
	ID        string    `json:"id"`
	Slug      string    `json:"slug"`
	Title     string    `json:"title"`
	StartTime time.Time `json:"startTime"`
	Live      bool      `json:"live"`
	Ended     bool      `json:"ended"`
	Score     string    `json:"score"`
	Period    string    `json:"period"`
	Teams     []team    `json:"teams"`
	Markets   []market  `json:"markets"`
}

type team struct {
	ID           int    `json:"id"`
	Name         string `json:"name"`
	Abbreviation string `json:"abbreviation"`
	SafeName     string `json:"safeName"`
	Color        string `json:"colorPrimary"`
}

type amount struct {
	Value string `json:"value"`
}

type marketsReply struct {
	Markets []market `json:"markets"`
}

type market struct {
	Slug           string  `json:"slug"`
	Type           string  `json:"sportsMarketType"`
	Line           float64 `json:"line"`
	FeeCoefficient float64 `json:"feeCoefficient"`
	Active         bool    `json:"active"`
	Closed         bool    `json:"closed"`
	BestBid        *amount `json:"bestBidQuote"`
	BestAsk        *amount `json:"bestAskQuote"`
	Sides          []struct {
		Long   bool `json:"long"`
		TeamID int  `json:"teamId"`
	} `json:"marketSides"`
}

// Events returns the league's games that haven't ended; none for a league
// Polymarket doesn't list.
func (c *Client) Events(ctx context.Context, league schema.League) ([]venue.Event, error) {
	slug, ok := leagues[league]
	if !ok {
		return nil, nil
	}
	var reply eventsReply
	if err := venue.GetJSON(ctx, c.HTTP, c.BaseURL+"/v2/leagues/"+slug+"/events?limit=100", &reply); err != nil {
		return nil, fmt.Errorf("polymarket: %w", err)
	}
	var out []venue.Event
	for _, e := range reply.Events {
		if e.Ended {
			continue
		}
		if ev, ok := convert(league, e); ok {
			out = append(out, ev)
		}
	}
	if err := c.addTotals(ctx, reply.Events, out); err != nil {
		return nil, fmt.Errorf("polymarket: %w", err)
	}
	return out, nil
}

// The highest lines asked for: Polymarket lists games' totals to 5.5 and
// teams' to 2.5 (asking for a slug it doesn't list costs nothing).
const (
	maxTotalLine = 5
	maxTeamLine  = 3
	slugsPerCall = 50
)

// total is what a total-goals slug is for.
type total struct {
	eventID string
	kind    schema.ContractKind
	outcome schema.Outcome
	line    float64
}

// addTotals fetches the games' total-goals and team-goals markets and adds
// them to the games' quotes.
func (c *Client) addTotals(ctx context.Context, events []event, out []venue.Event) error {
	wanted := map[string]total{}
	for _, e := range events {
		home, away, ok := sides(e)
		if e.Ended || !ok {
			continue
		}
		for n := 0; n <= maxTotalLine; n++ {
			wanted[fmt.Sprintf("tsc-%s-%dpt5", e.Slug, n)] = total{e.ID, schema.ContractKindTotal, schema.OutcomeOver, float64(n) + 0.5}
		}
		for _, side := range []struct {
			t       team
			outcome schema.Outcome
		}{{home, schema.OutcomeHome}, {away, schema.OutcomeAway}} {
			abbr := strings.ToLower(side.t.Abbreviation)
			if abbr == "" {
				continue
			}
			for n := 0; n <= maxTeamLine; n++ {
				wanted[fmt.Sprintf("tsc-%s-ttg-%s-%dpt5", e.Slug, abbr, n)] = total{e.ID, schema.ContractKindTeamTotal, side.outcome, float64(n) + 0.5}
			}
		}
	}
	slugs := slices.Sorted(maps.Keys(wanted))
	byEvent := map[string]*venue.Event{}
	for i := range out {
		byEvent[out[i].EventID] = &out[i]
	}
	for batch := range slices.Chunk(slugs, slugsPerCall) {
		q := url.Values{"slug": batch, "limit": {fmt.Sprint(2 * slugsPerCall)}}
		var reply marketsReply
		if err := venue.GetJSON(ctx, c.HTTP, c.BaseURL+"/v1/markets?"+q.Encode(), &reply); err != nil {
			return err
		}
		for _, m := range reply.Markets {
			w, ok := wanted[m.Slug]
			ev := byEvent[w.eventID]
			if !ok || ev == nil || !m.Active || m.Closed {
				continue
			}
			qt := quoteOf(m)
			qt.Kind, qt.Outcome, qt.Line = w.kind, w.outcome, w.line
			ev.Quotes = append(ev.Quotes, qt)
		}
	}
	return nil
}

// sides are the game's home and away teams. The title names the home team
// first: "Chelsea FC vs. Tottenham Hotspur FC".
func sides(e event) (home, away team, ok bool) {
	h, a, ok := strings.Cut(e.Title, " vs. ")
	if !ok || len(e.Teams) != 2 {
		return home, away, false
	}
	home, away = e.Teams[0], e.Teams[1]
	if strings.TrimSpace(h) != home.Name && strings.TrimSpace(a) == home.Name {
		home, away = away, home
	}
	return home, away, true
}

// quoteOf is a market's Yes (its long side) prices and fee.
func quoteOf(m market) venue.Quote {
	q := venue.Quote{MarketID: m.Slug, FeeCoefficient: m.FeeCoefficient, FeeCharged: true}
	if m.BestBid != nil {
		q.Bid = price(m.BestBid.Value)
	}
	if m.BestAsk != nil {
		q.Ask = price(m.BestAsk.Value)
	}
	return q
}

func convert(league schema.League, e event) (venue.Event, bool) {
	home, away, ok := sides(e)
	if !ok {
		return venue.Event{}, false
	}
	ev := venue.Event{
		Venue:   schema.VenuePolymarket,
		League:  league,
		EventID: e.ID,
		URL:     "https://polymarket.us/event/" + e.Slug,
		Home:    teamOf(home),
		Away:    teamOf(away),
		Kickoff: e.StartTime,
		State:   schema.GameStateScheduled,
	}
	if e.Live {
		ev.State = schema.GameStateLive
		ev.Clock = e.Period
	}
	if s, ok := score(e.Score); ok && e.Live {
		ev.Score = &s
	}
	for _, m := range e.Markets {
		if !m.Active || m.Closed || m.Type != "soccer_team_full_time_winner" {
			continue
		}
		q := quoteOf(m)
		q.Kind = schema.ContractKindResult
		switch outcome(m, home.ID, away.ID) {
		case "home":
			q.Outcome = schema.OutcomeHome
		case "away":
			q.Outcome = schema.OutcomeAway
		case "draw":
			q.Outcome = schema.OutcomeDraw
		default:
			continue
		}
		ev.Quotes = append(ev.Quotes, q)
	}
	return ev, true
}

// outcome says which result a winner market's Yes pays on: the team its long
// side is for, or a draw (a market for no team, its slug ending in -draw).
func outcome(m market, home, away int) string {
	if strings.HasSuffix(m.Slug, "-draw") {
		return "draw"
	}
	for _, s := range m.Sides {
		if !s.Long {
			continue
		}
		switch s.TeamID {
		case home:
			return "home"
		case away:
			return "away"
		}
	}
	return ""
}

func teamOf(t team) venue.Team {
	name := t.SafeName
	if name == "" {
		name = t.Name
	}
	vt := venue.Team{Name: name, Abbreviation: strings.ToUpper(t.Abbreviation)}
	if color.MatchString(t.Color) {
		vt.Color = t.Color
	}
	return vt
}

var (
	color      = regexp.MustCompile(`^#[0-9a-fA-F]{6}$`)
	scoreRegex = regexp.MustCompile(`^(\d+)-(\d+)$`)
)

func score(s string) (schema.MarketScore, bool) {
	m := scoreRegex.FindStringSubmatch(strings.TrimSpace(s))
	if m == nil {
		return schema.MarketScore{}, false
	}
	h, _ := strconv.Atoi(m[1])
	a, _ := strconv.Atoi(m[2])
	return schema.MarketScore{Home: h, Away: a}, true
}

func price(s string) *float64 {
	if p := venue.Dollars(s); p != nil {
		return venue.Price(*p)
	}
	return nil
}
