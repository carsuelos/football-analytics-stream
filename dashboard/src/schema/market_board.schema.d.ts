// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

export type League = "epl" | "laliga" | "bundesliga" | "mls" | "ucl";
export type Venue = "kalshi" | "polymarket" | "novig";
/**
 * From the venues: live once any says so, ended once any says so.
 */
export type GameState = "scheduled" | "live" | "ended";
/**
 * total: over line goals in regulation (90 minutes plus stoppage, no extra time or penalties). result: the outcome after regulation. team_total: one team scores over line goals in regulation.
 */
export type ContractKind = "total" | "result" | "team_total";
/**
 * What a Yes pays on: over the line (total); a home win, a draw or an away win (result); or the home or away team over the line (team_total).
 */
export type Outcome = "over" | "home" | "draw" | "away";
/**
 * The venue with the lowest all-in price that has contracts at its ask, if any.
 */
export type Venue1 = "kalshi" | "polymarket" | "novig";

/**
 * A league's games on the prediction markets (Kalshi, Polymarket US, Novig): each game matched across the venues that list it, its live state when a venue reports one, and every venue's price for the same contracts, with the cheapest all-in. Served by the markets service.
 */
export interface MarketBoard {
  /**
   * Wire-format version. Bump only for breaking changes.
   */
  schema_version: 1;
  league: League;
  /**
   * When the board was last rebuilt.
   */
  updated_at: string;
  /**
   * How each venue's last poll went.
   */
  venues: VenueStatus[];
  /**
   * Live games first, then by kick-off.
   */
  games: MarketGame[];
}
export interface VenueStatus {
  venue: Venue;
  /**
   * Whether its last poll succeeded.
   */
  ok: boolean;
  /**
   * Why it failed, if it did.
   */
  error?: string;
  /**
   * When its prices were last read.
   */
  updated_at?: string;
  /**
   * How many of the league's games it lists.
   */
  games: number;
}
export interface MarketGame {
  /**
   * Stable across polls, e.g. epl-2026-10-24-chelsea-tottenham.
   */
  id: string;
  league: League;
  home: MarketTeam;
  away: MarketTeam;
  kickoff: string;
  /**
   * Whether kickoff is estimated: Kalshi gives no kick-off time, so a game only Kalshi lists has one worked out from its markets' close.
   */
  kickoff_estimated?: boolean;
  state: GameState;
  score?: MarketScore;
  /**
   * The venue's match clock, e.g. 63' or HT.
   */
  clock?: string;
  listings: Listing[];
  contracts: Contract[];
}
export interface MarketTeam {
  name: string;
  /**
   * e.g. CFC
   */
  abbreviation?: string;
  /**
   * The team's colour, as #rrggbb, if a venue gives one.
   */
  color?: string;
}
export interface MarketScore {
  home: number;
  away: number;
}
/**
 * A venue's event for the game.
 */
export interface Listing {
  venue: Venue;
  event_id: string;
  /**
   * The event's page on the venue.
   */
  url?: string;
}
/**
 * One contract, priced on every venue that lists it.
 */
export interface Contract {
  /**
   * Stable within the game, e.g. total-over-2.5, result-draw or team-home-over-1.5.
   */
  key: string;
  kind: ContractKind;
  outcome: Outcome;
  /**
   * For total and team_total: the goals line, e.g. 2.5.
   */
  line?: number;
  /**
   * e.g. Over 2.5, Chelsea, Draw, Chelsea over 1.5.
   */
  label: string;
  quotes: Quote[];
  best?: Venue1;
  /**
   * The best all-in price as a probability: what the market says, after fees.
   */
  implied?: number;
}
/**
 * One venue's price to buy Yes, per contract that pays $1. Prices are dollars from 0 to 1.
 */
export interface Quote {
  venue: Venue;
  /**
   * The venue's market (Kalshi ticker, Polymarket slug, Novig market id).
   */
  market_id: string;
  /**
   * Best price someone will pay for Yes.
   */
  bid?: number;
  /**
   * Best price to buy Yes now.
   */
  ask?: number;
  /**
   * Contracts available at the ask.
   */
  ask_size?: number;
  /**
   * The taker fee per contract at the ask, by the venue's schedule (0 when it charges none, e.g. Novig before kick-off).
   */
  fee?: number;
  /**
   * ask + fee: what one contract costs.
   */
  all_in?: number;
  url?: string;
}
