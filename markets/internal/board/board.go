// Package board builds a league's market board: every game the venues list,
// matched across them, with each venue's price for the same contracts and the
// cheapest all-in (ask plus the venue's taker fee).
//
// A Board polls its venues in the background (Run): a league someone looked
// at in the last few minutes every Interval, the others every IdleInterval.
// A venue whose poll fails keeps its last good games for StaleAfter, and its
// status says why.
package board

import (
	"context"
	"fmt"
	"log/slog"
	"math"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/carsuelos/football-analytics-stream/markets/internal/schema"
	"github.com/carsuelos/football-analytics-stream/markets/internal/teams"
	"github.com/carsuelos/football-analytics-stream/markets/internal/venue"
)

// Leagues are the leagues a Board serves.
var Leagues = []schema.League{schema.LeagueEpl, schema.LeagueLaliga, schema.LeagueMls, schema.LeagueUcl}

// Board holds each league's latest board. Create it with New.
type Board struct {
	Sources      []venue.Source
	Interval     time.Duration // a league someone is looking at
	IdleInterval time.Duration // the others
	ActiveFor    time.Duration // how long a look keeps a league active
	StaleAfter   time.Duration // how long a failing venue's last games are kept
	PollTimeout  time.Duration
	// PollLive polls a league at Interval while one of its games is live or
	// about to kick off, even with no one looking (for recording).
	PollLive bool
	// OnBoard, if set, gets each league's board after every poll (outside the
	// board's lock).
	OnBoard func(schema.MarketBoard)
	Log     *slog.Logger
	Now     func() time.Time

	mu      sync.Mutex
	leagues map[schema.League]*league
	history *History
}

type league struct {
	refreshing sync.Mutex // one refresh at a time
	board      *schema.MarketBoard
	viewed     time.Time
	polled     time.Time
	venues     map[schema.Venue]*venueState
}

type venueState struct {
	events []venue.Event
	ok     time.Time // last success
	err    error
}

// New returns a board over sources with the default timings.
func New(sources []venue.Source, log *slog.Logger) *Board {
	return &Board{
		Sources:      sources,
		Interval:     10 * time.Second,
		IdleInterval: 2 * time.Minute,
		ActiveFor:    5 * time.Minute,
		StaleAfter:   2 * time.Minute,
		PollTimeout:  8 * time.Second,
		Log:          log,
		Now:          time.Now,
		leagues:      map[schema.League]*league{},
		history:      NewHistory(6*time.Hour, 1500),
	}
}

func (b *Board) state(l schema.League) *league {
	b.mu.Lock()
	defer b.mu.Unlock()
	s := b.leagues[l]
	if s == nil {
		s = &league{venues: map[schema.Venue]*venueState{}}
		b.leagues[l] = s
	}
	return s
}

// Get returns the league's board, polling the venues first if it has none
// yet, and marks the league as being looked at.
func (b *Board) Get(ctx context.Context, l schema.League) (schema.MarketBoard, error) {
	if !slices.Contains(Leagues, l) {
		return schema.MarketBoard{}, fmt.Errorf("unknown league %q", l)
	}
	s := b.state(l)
	b.mu.Lock()
	s.viewed = b.Now()
	have := s.board
	b.mu.Unlock()
	if have == nil {
		b.Refresh(ctx, l)
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	return *s.board, nil
}

// History returns a game's price history, if the board has seen the game.
func (b *Board) History(id string) (schema.PriceHistory, bool) {
	return b.history.Get(id)
}

// Run polls until ctx is done.
func (b *Board) Run(ctx context.Context) {
	tick := time.NewTicker(time.Second)
	defer tick.Stop()
	for {
		for _, l := range Leagues {
			s := b.state(l)
			b.mu.Lock()
			now := b.Now()
			every := b.IdleInterval
			if now.Sub(s.viewed) < b.ActiveFor || (b.PollLive && s.board != nil && busy(*s.board, now)) {
				every = b.Interval
			}
			due := now.Sub(s.polled) >= every
			b.mu.Unlock()
			if due {
				b.Refresh(ctx, l)
			}
		}
		select {
		case <-ctx.Done():
			return
		case <-tick.C:
		}
	}
}

// soon is how long before kick-off a game counts as busy.
const soon = 15 * time.Minute

// busy says whether a board has a game live or about to kick off.
func busy(board schema.MarketBoard, now time.Time) bool {
	for _, g := range board.Games {
		if g.State == schema.GameStateLive || (g.State == schema.GameStateScheduled && g.Kickoff.Sub(now) < soon) {
			return true
		}
	}
	return false
}

// Refresh polls every venue for the league at once and rebuilds its board.
func (b *Board) Refresh(ctx context.Context, l schema.League) {
	s := b.state(l)
	s.refreshing.Lock()
	defer s.refreshing.Unlock()
	ctx, cancel := context.WithTimeout(ctx, b.PollTimeout)
	defer cancel()
	type result struct {
		venue  schema.Venue
		events []venue.Event
		err    error
	}
	results := make(chan result, len(b.Sources))
	for _, src := range b.Sources {
		go func() {
			events, err := src.Events(ctx, l)
			results <- result{src.Venue(), events, err}
		}()
	}
	got := make([]result, 0, len(b.Sources))
	for range b.Sources {
		got = append(got, <-results)
	}

	b.mu.Lock()
	now := b.Now()
	s.polled = now
	for _, r := range got {
		vs := s.venues[r.venue]
		if vs == nil {
			vs = &venueState{}
			s.venues[r.venue] = vs
		}
		if r.err != nil {
			vs.err = r.err
			if b.Log != nil {
				b.Log.WarnContext(ctx, "venue poll failed", "venue", r.venue, "league", l, "err", r.err)
			}
			continue
		}
		vs.events, vs.ok, vs.err = r.events, now, nil
	}
	events := map[schema.Venue][]venue.Event{}
	var statuses []schema.VenueStatus
	for _, src := range b.Sources {
		v := src.Venue()
		vs := s.venues[v]
		st := schema.VenueStatus{Venue: v, Ok: vs.err == nil}
		if vs.err != nil {
			msg := vs.err.Error()
			st.Error = &msg
		}
		if !vs.ok.IsZero() {
			t := vs.ok
			st.UpdatedAt = &t
			if now.Sub(vs.ok) <= b.StaleAfter {
				events[v] = vs.events
				st.Games = len(vs.events)
			}
		}
		statuses = append(statuses, st)
	}
	board := Build(l, events, now)
	board.Venues = statuses
	s.board = &board
	b.history.Record(board)
	b.mu.Unlock()
	if b.OnBoard != nil {
		b.OnBoard(board)
	}
}

// Build matches the venues' events into games and prices each contract.
func Build(l schema.League, events map[schema.Venue][]venue.Event, now time.Time) schema.MarketBoard {
	var games []*game
	// Venues with kick-off times and the live state first, so they set the
	// game's kick-off and orientation; Kalshi's estimated kick-offs join them.
	for _, v := range []schema.Venue{schema.VenuePolymarket, schema.VenueNovig, schema.VenueKalshi} {
		for _, e := range events[v] {
			if e.League != l {
				continue
			}
			g := find(games, e)
			if g == nil {
				g = &game{league: l, kickoff: e.Kickoff, estimated: e.KickoffEstimated}
				games = append(games, g)
			}
			g.add(e)
		}
	}
	games = mergeSame(games)
	out := schema.MarketBoard{SchemaVersion: 1, League: l, UpdatedAt: now, Venues: []schema.VenueStatus{}, Games: []schema.MarketGame{}}
	for _, g := range games {
		mg := g.build(now)
		if mg.State == schema.GameStateEnded && now.Sub(mg.Kickoff) > 3*time.Hour {
			continue
		}
		out.Games = append(out.Games, mg)
	}
	slices.SortStableFunc(out.Games, func(a, b schema.MarketGame) int {
		if ra, rb := rank(a.State), rank(b.State); ra != rb {
			return ra - rb
		}
		return a.Kickoff.Compare(b.Kickoff)
	})
	return out
}

func rank(s schema.GameState) int {
	switch s {
	case schema.GameStateLive:
		return 0
	case schema.GameStateScheduled:
		return 1
	}
	return 2
}

// A game is the same game on every venue that lists it.
type game struct {
	league    schema.League
	kickoff   time.Time
	estimated bool
	homeNames []string
	awayNames []string
	events    []venue.Event
}

// sameDay is how far apart two venues' kick-offs for one game may be: Kalshi's
// are estimates, and a team plays at most once in it.
const sameDay = 30 * time.Hour

func find(games []*game, e venue.Event) *game {
	for _, g := range games {
		if g.league != e.League || absDuration(g.kickoff.Sub(e.Kickoff)) > sameDay {
			continue
		}
		if matchesAny(e.Home.Name, g.homeNames) && matchesAny(e.Away.Name, g.awayNames) {
			return g
		}
	}
	return nil
}

// mergeSame joins games that turn out to be one game. Which games an event
// joins depends on the order the venues come in: Polymarket's "Galatasaray SK"
// and Novig's "Galatasaray Spor Kulübü" don't match, but Kalshi's
// "Galatasaray", which comes last, matches both, so it bridges them.
func mergeSame(games []*game) []*game {
	for i := 0; i < len(games); i++ {
		for j := i + 1; j < len(games); j++ {
			if sameGame(games[i], games[j]) {
				for _, e := range games[j].events {
					games[i].add(e)
				}
				games = slices.Delete(games, j, j+1)
				j = i // games[i] has new names: look again
			}
		}
	}
	return games
}

// sameGame reports whether two games are one: no venue in both (a venue lists
// a game once), kick-offs close, and both teams named alike somewhere.
func sameGame(a, b *game) bool {
	if a.league != b.league || absDuration(a.kickoff.Sub(b.kickoff)) > sameDay {
		return false
	}
	for _, ea := range a.events {
		for _, eb := range b.events {
			if ea.Venue == eb.Venue {
				return false
			}
		}
	}
	for _, n := range b.homeNames {
		if !matchesAny(n, a.homeNames) {
			continue
		}
		for _, m := range b.awayNames {
			if matchesAny(m, a.awayNames) {
				return true
			}
		}
	}
	return false
}

func matchesAny(name string, names []string) bool {
	for _, n := range names {
		if teams.Same(name, n) {
			return true
		}
	}
	return false
}

func (g *game) add(e venue.Event) {
	// The first venue's kick-off stands, unless it was an estimate.
	if g.estimated && !e.KickoffEstimated {
		g.kickoff, g.estimated = e.Kickoff, false
	}
	g.homeNames = append(g.homeNames, e.Home.Name)
	g.awayNames = append(g.awayNames, e.Away.Name)
	g.events = append(g.events, e)
}

// pick returns the first non-empty value, trying the venues in order.
func (g *game) pick(order []schema.Venue, value func(venue.Event) string) string {
	for _, v := range order {
		for _, e := range g.events {
			if e.Venue == v {
				if s := value(e); s != "" {
					return s
				}
			}
		}
	}
	return ""
}

var (
	// Kalshi's short names read best ("Chelsea", "Bilbao"), then Polymarket's;
	// for MLS, Kalshi clips them ("Los Angeles F", "New York RB"), so
	// Polymarket's come first.
	nameOrder    = []schema.Venue{schema.VenueKalshi, schema.VenuePolymarket, schema.VenueNovig}
	mlsNameOrder = []schema.Venue{schema.VenuePolymarket, schema.VenueNovig, schema.VenueKalshi}
	// Polymarket gives abbreviations and colours for every team.
	styleOrder = []schema.Venue{schema.VenuePolymarket, schema.VenueKalshi, schema.VenueNovig}
)

func (g *game) team(side func(venue.Event) venue.Team) schema.MarketTeam {
	order := nameOrder
	if g.league == schema.LeagueMls {
		order = mlsNameOrder
	}
	t := schema.MarketTeam{Name: g.pick(order, func(e venue.Event) string { return side(e).Name })}
	if a := g.pick(styleOrder, func(e venue.Event) string { return side(e).Abbreviation }); a != "" {
		t.Abbreviation = &a
	}
	if c := g.pick(styleOrder, func(e venue.Event) string { return side(e).Color }); c != "" {
		t.Color = &c
	}
	return t
}

// liveFor is how long after kick-off a game is taken to be in play when no
// venue says either way.
const liveFor = 2*time.Hour + 15*time.Minute

func (g *game) build(now time.Time) schema.MarketGame {
	home := g.team(func(e venue.Event) venue.Team { return e.Home })
	away := g.team(func(e venue.Event) venue.Team { return e.Away })
	mg := schema.MarketGame{
		ID:        id(g.league, g.kickoff, home.Name, away.Name),
		League:    g.league,
		Home:      home,
		Away:      away,
		Kickoff:   g.kickoff,
		State:     schema.GameStateScheduled,
		Listings:  []schema.Listing{},
		Contracts: []schema.Contract{},
	}
	if g.estimated {
		est := true
		mg.KickoffEstimated = &est
	}
	said := false
	for _, e := range g.events {
		l := schema.Listing{Venue: e.Venue, EventID: e.EventID}
		if e.URL != "" {
			u := e.URL
			l.Url = &u
		}
		mg.Listings = append(mg.Listings, l)
		switch e.State {
		case schema.GameStateLive:
			mg.State, said = schema.GameStateLive, true
		case schema.GameStateScheduled:
			said = true
		}
		if e.Score != nil && mg.Score == nil {
			s := *e.Score
			mg.Score = &s
		}
		if e.Clock != "" && mg.Clock == nil {
			c := e.Clock
			mg.Clock = &c
		}
	}
	if !said || mg.State != schema.GameStateLive {
		switch {
		case now.Before(g.kickoff):
		case now.Sub(g.kickoff) < liveFor:
			if !said || g.estimated {
				mg.State = schema.GameStateLive
			}
		default:
			mg.State = schema.GameStateEnded
		}
	}
	mg.Contracts = g.contracts(home.Name, away.Name)
	return mg
}

func id(l schema.League, kickoff time.Time, home, away string) string {
	slug := func(name string) string { return strings.ReplaceAll(teams.Key(name), " ", "-") }
	return fmt.Sprintf("%s-%s-%s-%s", l, kickoff.UTC().Format("2006-01-02"), slug(home), slug(away))
}

var kindOrder = map[schema.ContractKind]int{schema.ContractKindTotal: 0, schema.ContractKindResult: 1, schema.ContractKindTeamTotal: 2}

var outcomeOrder = map[schema.Outcome]int{schema.OutcomeHome: 0, schema.OutcomeDraw: 1, schema.OutcomeAway: 2}

func (g *game) contracts(home, away string) []schema.Contract {
	byKey := map[string]*schema.Contract{}
	var keys []string
	for _, e := range g.events {
		for _, q := range e.Quotes {
			if (q.Kind == schema.ContractKindTotal && q.Line > maxLine) || (q.Kind == schema.ContractKindTeamTotal && q.Line > maxTeamLine) {
				continue
			}
			key, label := contractKey(q, home, away)
			c := byKey[key]
			if c == nil {
				c = &schema.Contract{Key: key, Kind: q.Kind, Outcome: q.Outcome, Label: label, Quotes: []schema.Quote{}}
				if q.Kind != schema.ContractKindResult {
					line := q.Line
					c.Line = &line
				}
				byKey[key] = c
				keys = append(keys, key)
			}
			c.Quotes = append(c.Quotes, priced(e.Venue, q))
		}
	}
	out := make([]schema.Contract, 0, len(keys))
	for _, k := range keys {
		c := byKey[k]
		best(c)
		out = append(out, *c)
	}
	// Totals by line, then the result, then each team's goals by line.
	slices.SortStableFunc(out, func(a, b schema.Contract) int {
		if a.Kind != b.Kind {
			return kindOrder[a.Kind] - kindOrder[b.Kind]
		}
		if a.Outcome != b.Outcome {
			return outcomeOrder[a.Outcome] - outcomeOrder[b.Outcome]
		}
		if a.Line != nil && b.Line != nil {
			return cmpFloat(*a.Line, *b.Line)
		}
		return 0
	})
	return out
}

// maxLine is the highest total-goals line shown: Kalshi lists up to 6.5,
// and Novig's lines past it only have token orders.
const maxLine = 6.5

// maxTeamLine is the highest team-goals line shown (no venue lists past it
// with real orders).
const maxTeamLine = 3.5

func contractKey(q venue.Quote, home, away string) (key, label string) {
	if q.Kind == schema.ContractKindTotal {
		return fmt.Sprintf("total-over-%g", q.Line), fmt.Sprintf("Over %g", q.Line)
	}
	label = map[schema.Outcome]string{schema.OutcomeHome: home, schema.OutcomeAway: away, schema.OutcomeDraw: "Draw"}[q.Outcome]
	if q.Kind == schema.ContractKindTeamTotal {
		return fmt.Sprintf("team-%s-over-%g", q.Outcome, q.Line), fmt.Sprintf("%s over %g", label, q.Line)
	}
	return "result-" + string(q.Outcome), label
}

// priced is the quote as the board shows it, with its fee and all-in price.
func priced(v schema.Venue, q venue.Quote) schema.Quote {
	out := schema.Quote{Venue: v, MarketID: q.MarketID, Bid: round(q.Bid), Ask: round(q.Ask), AskSize: q.AskSize}
	if q.URL != "" {
		u := q.URL
		out.Url = &u
	}
	if q.Ask != nil {
		fee := q.Fee(*q.Ask)
		allIn := *q.Ask + fee
		out.Fee, out.AllIn = round(&fee), round(&allIn)
	}
	return out
}

// best marks the venue with the lowest all-in price that has contracts at it.
func best(c *schema.Contract) {
	var top *schema.Quote
	for i := range c.Quotes {
		q := &c.Quotes[i]
		if q.AllIn == nil || (q.AskSize != nil && *q.AskSize <= 0) {
			continue
		}
		if top == nil || *q.AllIn < *top.AllIn {
			top = q
		}
	}
	if top != nil {
		v, implied := top.Venue, math.Min(*top.AllIn, 1)
		c.Best, c.Implied = &v, &implied
	}
}

func round(p *float64) *float64 {
	if p == nil {
		return nil
	}
	r := math.Round(*p*1e5) / 1e5
	return &r
}

func cmpFloat(a, b float64) int {
	switch {
	case a < b:
		return -1
	case a > b:
		return 1
	}
	return 0
}

func absDuration(d time.Duration) time.Duration {
	if d < 0 {
		return -d
	}
	return d
}
