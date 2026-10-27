// Package kalshi reads Kalshi's soccer markets: per game, total goals (over
// 0.5 to 6.5), the result (each team, and a tie) and each team's goals (over
// 0.5 to 2.5), all settled on 90 minutes plus stoppage time. Reading needs no
// key.
//
// Kalshi lists each kind of market as its own series of events (for the
// Premier League, KXEPLTOTAL, KXEPLGAME and KXEPLTEAMTOTAL), so a game is the
// events of the series that share a suffix: KXEPLTOTAL-26OCT24CFCTOT and
// KXEPLGAME-26OCT24CFCTOT are Chelsea v Tottenham on Oct 24, 2026. Kalshi
// gives no kick-off time; it is estimated from when the markets are expected
// to close.
package kalshi

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	"github.com/carsuelos/football-analytics-stream/markets/internal/schema"
	"github.com/carsuelos/football-analytics-stream/markets/internal/venue"
)

// DefaultBaseURL is Kalshi's production API.
const DefaultBaseURL = "https://api.elections.kalshi.com/trade-api/v2"

// FeeCoefficient is Kalshi's quadratic taker fee: 0.07 * p * (1 - p) a
// contract (the series' fee_multiplier is 1 for these).
const FeeCoefficient = 0.07

// series are each league's total-goals, result and team-goals series.
var series = map[schema.League]struct{ total, game, teamTotal string }{
	schema.LeagueEpl:        {"KXEPLTOTAL", "KXEPLGAME", "KXEPLTEAMTOTAL"},
	schema.LeagueLaliga:     {"KXLALIGATOTAL", "KXLALIGAGAME", "KXLALIGATEAMTOTAL"},
	schema.LeagueBundesliga: {"KXBUNDESLIGATOTAL", "KXBUNDESLIGAGAME", "KXBUNDESLIGATEAMTOTAL"},
	schema.LeagueMls:        {"KXMLSTOTAL", "KXMLSGAME", "KXMLSTEAMTOTAL"},
	schema.LeagueUcl:        {"KXUCLTOTAL", "KXUCLGAME", "KXUCLTEAMTOTAL"},
}

// How long after kick-off each series' markets are expected to close, which
// is how kick-off is estimated. (Team goals close with the result.)
const (
	totalCloses = 4 * time.Hour
	gameCloses  = 3 * time.Hour
)

// Client reads Kalshi. The zero value is not usable; set BaseURL and HTTP.
type Client struct {
	BaseURL string
	HTTP    *http.Client
}

// New returns a client for Kalshi's production API.
func New(httpClient *http.Client) *Client {
	return &Client{BaseURL: DefaultBaseURL, HTTP: httpClient}
}

func (c *Client) Venue() schema.Venue { return schema.VenueKalshi }

type eventsReply struct {
	Events []event `json:"events"`
	Cursor string  `json:"cursor"`
}

type event struct {
	EventTicker string   `json:"event_ticker"`
	Title       string   `json:"title"`
	SubTitle    string   `json:"sub_title"`
	Markets     []market `json:"markets"`
}

type market struct {
	Ticker                 string    `json:"ticker"`
	Status                 string    `json:"status"`
	YesSubTitle            string    `json:"yes_sub_title"`
	YesBid                 string    `json:"yes_bid_dollars"`
	YesAsk                 string    `json:"yes_ask_dollars"`
	YesAskSize             string    `json:"yes_ask_size_fp"`
	FloorStrike            *float64  `json:"floor_strike"`
	StrikeType             string    `json:"strike_type"`
	ExpectedExpirationTime time.Time `json:"expected_expiration_time"`
	RulesPrimary           string    `json:"rules_primary"`
}

// Events returns the league's open games, with all three series' markets.
func (c *Client) Events(ctx context.Context, league schema.League) ([]venue.Event, error) {
	s, ok := series[league]
	if !ok {
		return nil, fmt.Errorf("kalshi: no series for league %q", league)
	}
	games := map[string]*venue.Event{}
	var order []string
	for _, ticker := range []string{s.total, s.game, s.teamTotal} {
		kind := map[string]schema.ContractKind{
			s.total: schema.ContractKindTotal, s.game: schema.ContractKindResult, s.teamTotal: schema.ContractKindTeamTotal,
		}[ticker]
		events, err := c.events(ctx, ticker)
		if err != nil {
			return nil, err
		}
		for _, e := range events {
			key, ok := strings.CutPrefix(e.EventTicker, ticker+"-")
			if !ok {
				continue
			}
			g := games[key]
			if g == nil {
				home, away, ok := teams(e.Title, e.SubTitle)
				if !ok {
					continue
				}
				g = &venue.Event{Venue: schema.VenueKalshi, League: league, EventID: key, Home: home, Away: away, KickoffEstimated: true}
				if day, ok := date(key); ok {
					g.Kickoff = day
				}
				games[key] = g
				order = append(order, key)
			}
			for _, m := range e.Markets {
				if m.Status != "active" {
					continue
				}
				q, ok := quote(kind, m, g)
				if !ok {
					continue
				}
				g.Quotes = append(g.Quotes, q)
				closes := gameCloses
				if kind == schema.ContractKindTotal {
					closes = totalCloses
				}
				if !m.ExpectedExpirationTime.IsZero() {
					g.Kickoff = m.ExpectedExpirationTime.Add(-closes)
				}
			}
		}
	}
	out := make([]venue.Event, 0, len(order))
	for _, key := range order {
		out = append(out, *games[key])
	}
	return out, nil
}

func (c *Client) events(ctx context.Context, seriesTicker string) ([]event, error) {
	var all []event
	cursor := ""
	for page := 0; page < 10; page++ {
		q := url.Values{
			"series_ticker":       {seriesTicker},
			"status":              {"open"},
			"with_nested_markets": {"true"},
			"limit":               {"200"},
		}
		if cursor != "" {
			q.Set("cursor", cursor)
		}
		var reply eventsReply
		if err := venue.GetJSON(ctx, c.HTTP, c.BaseURL+"/events?"+q.Encode(), &reply); err != nil {
			return nil, fmt.Errorf("kalshi: %w", err)
		}
		all = append(all, reply.Events...)
		if reply.Cursor == "" || len(reply.Events) == 0 {
			break
		}
		cursor = reply.Cursor
	}
	return all, nil
}

var subTitle = regexp.MustCompile(`^([A-Z0-9]+) vs ([A-Z0-9]+)`)

// teams reads "Chelsea vs Tottenham: Total Goals" and "CFC vs TOT (Oct 24)".
func teams(title, sub string) (home, away venue.Team, ok bool) {
	title, _, _ = strings.Cut(title, ":")
	h, a, ok := strings.Cut(title, " vs ")
	if !ok {
		return home, away, false
	}
	home.Name, away.Name = strings.TrimSpace(h), strings.TrimSpace(a)
	if m := subTitle.FindStringSubmatch(sub); m != nil {
		home.Abbreviation, away.Abbreviation = m[1], m[2]
	}
	return home, away, home.Name != "" && away.Name != ""
}

// date reads the day from an event key such as 26OCT24CFCTOT.
func date(key string) (time.Time, bool) {
	if len(key) < 7 {
		return time.Time{}, false
	}
	d, err := time.Parse("06Jan02", key[:2]+strings.ToUpper(key[2:3])+strings.ToLower(key[3:5])+key[5:7])
	if err != nil {
		return time.Time{}, false
	}
	return d.Add(12 * time.Hour), true
}

func quote(kind schema.ContractKind, m market, g *venue.Event) (venue.Quote, bool) {
	q := venue.Quote{
		MarketID:       m.Ticker,
		Bid:            price(m.YesBid),
		Ask:            price(m.YesAsk),
		AskSize:        venue.Dollars(m.YesAskSize),
		FeeCoefficient: FeeCoefficient,
		FeeCharged:     true,
	}
	suffix := m.Ticker[strings.LastIndex(m.Ticker, "-")+1:]
	switch kind {
	case schema.ContractKindTotal:
		if m.FloorStrike == nil || m.StrikeType != "greater" {
			return q, false
		}
		q.Kind, q.Outcome, q.Line = kind, schema.OutcomeOver, *m.FloorStrike
		return q, true
	case schema.ContractKindTeamTotal:
		// CFC2: Chelsea over 1.5.
		if m.FloorStrike == nil || m.StrikeType != "greater" {
			return q, false
		}
		q.Kind, q.Line = kind, *m.FloorStrike
		switch strings.TrimRight(suffix, "0123456789") {
		case g.Home.Abbreviation:
			q.Outcome = schema.OutcomeHome
		case g.Away.Abbreviation:
			q.Outcome = schema.OutcomeAway
		default:
			return q, false
		}
		return q, true
	}
	q.Kind = schema.ContractKindResult
	switch {
	case suffix == "TIE":
		q.Outcome = schema.OutcomeDraw
	case suffix == g.Home.Abbreviation, m.YesSubTitle == g.Home.Name:
		q.Outcome = schema.OutcomeHome
	case suffix == g.Away.Abbreviation, m.YesSubTitle == g.Away.Name:
		q.Outcome = schema.OutcomeAway
	default:
		return q, false
	}
	return q, true
}

func price(s string) *float64 {
	if p := venue.Dollars(s); p != nil {
		return venue.Price(*p)
	}
	return nil
}
