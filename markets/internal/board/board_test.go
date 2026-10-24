package board

import (
	"context"
	"errors"
	"math"
	"slices"
	"testing"
	"time"

	"github.com/carsuelos/football-analytics-stream/markets/internal/schema"
	"github.com/carsuelos/football-analytics-stream/markets/internal/venue"
)

var kickoff = time.Date(2026, 10, 24, 16, 30, 0, 0, time.UTC)

func p(v float64) *float64 { return &v }

func q(kind schema.ContractKind, o schema.Outcome, line, bid, ask float64, coef float64) venue.Quote {
	return venue.Quote{Kind: kind, Outcome: o, Line: line, MarketID: "m", Bid: p(bid), Ask: p(ask), FeeCoefficient: coef, FeeCharged: coef > 0}
}

func chelsea() map[schema.Venue][]venue.Event {
	return map[schema.Venue][]venue.Event{
		schema.VenueKalshi: {{
			Venue: schema.VenueKalshi, League: schema.LeagueEpl, EventID: "26OCT24CFCTOT",
			Home: venue.Team{Name: "Chelsea", Abbreviation: "CFC"}, Away: venue.Team{Name: "Tottenham", Abbreviation: "TOT"},
			Kickoff: kickoff.Add(30 * time.Minute), KickoffEstimated: true,
			Quotes: []venue.Quote{
				q(schema.ContractKindTotal, schema.OutcomeOver, 0.5, 0.75, 0.80, 0.07),
				q(schema.ContractKindTeamTotal, schema.OutcomeAway, 0.5, 0.55, 0.58, 0.07),
				q(schema.ContractKindTotal, schema.OutcomeOver, 1.5, 0.30, 0.37, 0.07),
				q(schema.ContractKindResult, schema.OutcomeDraw, 0, 0.45, 0.46, 0.07),
				q(schema.ContractKindTeamTotal, schema.OutcomeHome, 1.5, 0.40, 0.42, 0.07),
				q(schema.ContractKindTeamTotal, schema.OutcomeHome, 4.5, 0.01, 0.02, 0.07),
			},
		}},
		schema.VenuePolymarket: {{
			Venue: schema.VenuePolymarket, League: schema.LeagueEpl, EventID: "164610", URL: "https://polymarket.us/event/x",
			Home: venue.Team{Name: "Chelsea", Abbreviation: "CFC", Color: "#034694"}, Away: venue.Team{Name: "Tottenham Hotspur", Abbreviation: "TOT"},
			Kickoff: kickoff, State: schema.GameStateLive, Score: &schema.MarketScore{Home: 1, Away: 0}, Clock: "63'",
			Quotes: []venue.Quote{q(schema.ContractKindResult, schema.OutcomeDraw, 0, 0.45, 0.455, 0.0695)},
		}},
		schema.VenueNovig: {{
			Venue: schema.VenueNovig, League: schema.LeagueEpl, EventID: "nv-1",
			Home: venue.Team{Name: "Chelsea FC"}, Away: venue.Team{Name: "Tottenham Hotspur FC"},
			Kickoff: kickoff, State: schema.GameStateLive,
			Quotes: []venue.Quote{
				q(schema.ContractKindTotal, schema.OutcomeOver, 0.5, 0.77, 0.79, 0.06),
				q(schema.ContractKindResult, schema.OutcomeDraw, 0, 0.44, 0.465, 0.06),
			},
		}},
	}
}

func TestBuildMatchesAGameAcrossTheVenues(t *testing.T) {
	b := Build(schema.LeagueEpl, chelsea(), kickoff.Add(time.Hour))
	if len(b.Games) != 1 {
		t.Fatalf("%d games: %+v", len(b.Games), b.Games)
	}
	g := b.Games[0]
	if g.ID != "epl-2026-10-24-chelsea-tottenham" || g.Home.Name != "Chelsea" || g.Away.Name != "Tottenham" ||
		*g.Home.Color != "#034694" || *g.Away.Abbreviation != "TOT" || !g.Kickoff.Equal(kickoff) || g.KickoffEstimated != nil {
		t.Errorf("game = %+v", g)
	}
	if g.State != schema.GameStateLive || *g.Score != (schema.MarketScore{Home: 1, Away: 0}) || *g.Clock != "63'" || len(g.Listings) != 3 {
		t.Errorf("state %v score %v clock %v listings %v", g.State, g.Score, g.Clock, g.Listings)
	}
	keys := []string{}
	for _, c := range g.Contracts {
		keys = append(keys, c.Key)
	}
	// Totals, the result, then each team's goals; past 3.5 a team's line isn't shown.
	want := []string{"total-over-0.5", "total-over-1.5", "result-draw", "team-home-over-1.5", "team-away-over-0.5"}
	if !slices.Equal(keys, want) {
		t.Errorf("contracts %v, want %v", keys, want)
	}
	over := g.Contracts[0]
	// Kalshi 0.80 + 0.07*0.8*0.2 = 0.8112; Novig 0.79 + 0.06*0.79*0.21 = 0.799954.
	if len(over.Quotes) != 2 || *over.Best != schema.VenueNovig || math.Abs(*over.Implied-0.79995) > 1e-9 {
		t.Errorf("over 0.5: best %v implied %v quotes %+v", *over.Best, *over.Implied, over.Quotes)
	}
	draw := g.Contracts[2]
	// Polymarket 0.455 + 0.0695*0.455*0.545 = 0.47223; Kalshi 0.46 + 0.07*0.46*0.54 = 0.47739; Novig 0.465 + 0.01493.
	if len(draw.Quotes) != 3 || *draw.Best != schema.VenuePolymarket || draw.Label != "Draw" {
		t.Errorf("draw: best %v quotes %+v", *draw.Best, draw.Quotes)
	}
	if c := g.Contracts[3]; c.Kind != schema.ContractKindTeamTotal || c.Label != "Chelsea over 1.5" || *c.Line != 1.5 {
		t.Errorf("team total %+v", c)
	}
}

func TestDifferentGamesStayApart(t *testing.T) {
	events := chelsea()
	pm := events[schema.VenuePolymarket][0]
	pm.Home, pm.Away = venue.Team{Name: "Crystal Palace"}, venue.Team{Name: "Newcastle United"}
	pm.Kickoff = kickoff.Add(21*time.Hour + 30*time.Minute)
	pm.State, pm.Score, pm.Clock = schema.GameStateScheduled, nil, ""
	events[schema.VenuePolymarket] = append(events[schema.VenuePolymarket], pm)
	// Chelsea again a week later: a different game.
	nv := events[schema.VenueNovig][0]
	nv.Kickoff, nv.State = kickoff.Add(7*24*time.Hour), schema.GameStateScheduled
	events[schema.VenueNovig] = append(events[schema.VenueNovig], nv)
	b := Build(schema.LeagueEpl, events, kickoff.Add(time.Hour))
	var ids []string
	for _, g := range b.Games {
		ids = append(ids, g.ID+"/"+string(g.State))
	}
	want := []string{"epl-2026-10-24-chelsea-tottenham/live", "epl-2026-10-25-crystal-palace-newcastle/scheduled", "epl-2026-10-31-chelsea-tottenham/scheduled"}
	if !slices.Equal(ids, want) {
		t.Errorf("games %v, want %v", ids, want)
	}
}

func TestAGameOnlyKalshiListsHasAnEstimatedKickoffAndIsLiveByTheClock(t *testing.T) {
	events := map[schema.Venue][]venue.Event{schema.VenueKalshi: chelsea()[schema.VenueKalshi]}
	at := func(after time.Duration) schema.MarketGame {
		return Build(schema.LeagueEpl, events, kickoff.Add(30*time.Minute+after)).Games[0]
	}
	if g := at(-time.Minute); g.State != schema.GameStateScheduled || g.KickoffEstimated == nil || !*g.KickoffEstimated {
		t.Errorf("before kick-off: %v %v", g.State, g.KickoffEstimated)
	}
	if g := at(time.Hour); g.State != schema.GameStateLive {
		t.Errorf("an hour in: %v", g.State)
	}
	if g := at(2*time.Hour + 30*time.Minute); g.State != schema.GameStateEnded {
		t.Errorf("after: %v", g.State)
	}
	if n := len(Build(schema.LeagueEpl, events, kickoff.Add(4*time.Hour)).Games); n != 0 {
		t.Errorf("long over, still %d games", n)
	}
}

func TestNoBestWithoutContractsAtTheAsk(t *testing.T) {
	c := schema.Contract{Quotes: []schema.Quote{{Venue: schema.VenueKalshi, AllIn: p(0.5), AskSize: p(0)}, {Venue: schema.VenueNovig}}}
	best(&c)
	if c.Best != nil {
		t.Errorf("best %v", *c.Best)
	}
}

type source struct {
	v      schema.Venue
	events []venue.Event
	err    error
}

func (s *source) Venue() schema.Venue { return s.v }
func (s *source) Events(context.Context, schema.League) ([]venue.Event, error) {
	return s.events, s.err
}

func TestAFailingVenueKeepsItsLastGamesForAWhile(t *testing.T) {
	ev := chelsea()
	kal := &source{v: schema.VenueKalshi, events: ev[schema.VenueKalshi]}
	pm := &source{v: schema.VenuePolymarket, events: ev[schema.VenuePolymarket]}
	now := kickoff.Add(time.Hour)
	b := New([]venue.Source{kal, pm}, nil)
	b.Now = func() time.Time { return now }

	got, err := b.Get(context.Background(), schema.LeagueEpl)
	if err != nil || len(got.Games) != 1 || len(got.Games[0].Listings) != 2 {
		t.Fatalf("board %+v, %v", got, err)
	}
	pm.err = errors.New("polymarket: 503")
	now = now.Add(time.Minute)
	b.Refresh(context.Background(), schema.LeagueEpl)
	got, _ = b.Get(context.Background(), schema.LeagueEpl)
	st := got.Venues[1]
	if st.Venue != schema.VenuePolymarket || st.Ok || *st.Error != "polymarket: 503" || st.Games != 1 || len(got.Games[0].Listings) != 2 {
		t.Errorf("a minute later: %+v, %d listings", st, len(got.Games[0].Listings))
	}
	now = now.Add(2 * time.Minute)
	b.Refresh(context.Background(), schema.LeagueEpl)
	got, _ = b.Get(context.Background(), schema.LeagueEpl)
	if st := got.Venues[1]; st.Games != 0 || len(got.Games[0].Listings) != 1 {
		t.Errorf("three minutes later: %+v, %d listings", st, len(got.Games[0].Listings))
	}
	if _, err := b.Get(context.Background(), "seriea"); err == nil {
		t.Error("an unknown league")
	}
}

func TestHistoryKeepsEachChangeAndAQuietPointAMinute(t *testing.T) {
	h := NewHistory(time.Hour, 3)
	board := func(at time.Duration, price float64) schema.MarketBoard {
		v := schema.VenueKalshi
		return schema.MarketBoard{UpdatedAt: kickoff.Add(at), Games: []schema.MarketGame{{
			ID: "g", Contracts: []schema.Contract{{Key: "total-over-0.5", Best: &v, Implied: p(price)}, {Key: "result-draw"}},
		}}}
	}
	for _, step := range []struct {
		at    time.Duration
		price float64
	}{{0, 0.5}, {10 * time.Second, 0.5}, {20 * time.Second, 0.6}, {90 * time.Second, 0.6}, {100 * time.Second, 0.7}} {
		h.Record(board(step.at, step.price))
	}
	got, ok := h.Get("g")
	if !ok || len(got.Series) != 1 {
		t.Fatalf("%+v %v", got, ok)
	}
	var prices []float64
	for _, pt := range got.Series[0].Points {
		prices = append(prices, pt.AllIn)
	}
	// 0.5 (dropped at the limit of 3), 0.6, 0.6 a minute later, 0.7.
	if len(prices) != 3 || prices[0] != 0.6 || prices[1] != 0.6 || prices[2] != 0.7 {
		t.Errorf("points %v", prices)
	}
	h.Record(schema.MarketBoard{UpdatedAt: kickoff.Add(2 * time.Hour)})
	if _, ok := h.Get("g"); ok {
		t.Error("a game unseen for longer than keep is forgotten")
	}
}
