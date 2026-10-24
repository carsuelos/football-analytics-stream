// Package polymarket reads Polymarket US's soccer games: each game's result
// markets (each team to win, and a draw, after regulation time), and the live
// score and clock, which Polymarket's sports data reports. Reading needs no
// key. (It lists no per-game total goals for these leagues yet; if it starts
// to, they would come as markets of a total type and need adding here.)
package polymarket

import (
	"context"
	"fmt"
	"net/http"
	"regexp"
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
	schema.LeagueEpl:    "epl",
	schema.LeagueLaliga: "lal",
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

type market struct {
	Slug           string  `json:"slug"`
	Type           string  `json:"sportsMarketType"`
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

// Events returns the league's games that haven't ended.
func (c *Client) Events(ctx context.Context, league schema.League) ([]venue.Event, error) {
	slug, ok := leagues[league]
	if !ok {
		return nil, fmt.Errorf("polymarket: no league %q", league)
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
	return out, nil
}

func convert(league schema.League, e event) (venue.Event, bool) {
	// The title names the home team first: "Chelsea FC vs. Tottenham Hotspur FC".
	h, a, ok := strings.Cut(e.Title, " vs. ")
	if !ok || len(e.Teams) != 2 {
		return venue.Event{}, false
	}
	home, away := e.Teams[0], e.Teams[1]
	if strings.TrimSpace(h) != home.Name && strings.TrimSpace(a) == home.Name {
		home, away = away, home
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
		q := venue.Quote{
			Kind:           schema.ContractKindResult,
			MarketID:       m.Slug,
			FeeCoefficient: m.FeeCoefficient,
			FeeCharged:     true,
		}
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
		if m.BestBid != nil {
			q.Bid = price(m.BestBid.Value)
		}
		if m.BestAsk != nil {
			q.Ask = price(m.BestAsk.Value)
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
