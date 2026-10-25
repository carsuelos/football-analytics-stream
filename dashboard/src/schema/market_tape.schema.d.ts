// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

export type League = "epl" | "laliga" | "mls";
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
export type Venue = "kalshi" | "polymarket" | "novig";

/**
 * One line of a market tape: the markets service's record of a game's prices on every venue, written to data/markets/<UTC date>/<league>.jsonl while it runs with recording on, so trading strategies can be replayed against real prices. A keyframe has the game's whole state; the lines after it until the next keyframe have only what changed (quotes that moved, and quotes no longer listed). Replaying a game: start from a keyframe and apply each line in order. Prices are dollars from 0 to 1 for a contract paying $1.
 */
export interface MarketTapeRecord {
  /**
   * Wire-format version. Bump only for breaking changes.
   */
  schema_version: 1;
  /**
   * When the board was built from the venues' replies.
   */
  t: string;
  league: League;
  /**
   * The board's game id, e.g. epl-2026-10-24-chelsea-tottenham.
   */
  game_id: string;
  /**
   * Whether this line has the game's whole state; otherwise only what changed since the line before.
   */
  keyframe: boolean;
  /**
   * Keyframes only.
   */
  home?: string;
  /**
   * Keyframes only.
   */
  away?: string;
  /**
   * Keyframes only.
   */
  kickoff?: string;
  state: GameState;
  score?: MarketScore;
  /**
   * The venue's clock, e.g. 63' or HT.
   */
  clock?: string;
  /**
   * Keyframes only: what each contract key in the quotes is.
   */
  contracts?: TapeContract[];
  /**
   * A keyframe's every quote, or the quotes that changed.
   */
  quotes: TapeQuote[];
  /**
   * Quotes listed in the line before and not any more.
   */
  gone?: TapeGone[];
}
export interface MarketScore {
  home: number;
  away: number;
}
export interface TapeContract {
  key: string;
  kind: ContractKind;
  outcome: Outcome;
  line?: number;
}
export interface TapeQuote {
  contract: string;
  venue: Venue;
  bid?: number;
  ask?: number;
  /**
   * Contracts at the ask.
   */
  ask_size?: number;
  /**
   * The taker fee per contract at the ask.
   */
  fee?: number;
}
export interface TapeGone {
  contract: string;
  venue: Venue;
}
