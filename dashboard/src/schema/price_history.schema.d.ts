// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

export type Venue = "kalshi" | "polymarket" | "novig";

/**
 * How a game's contracts have been priced since the markets service started watching it: the best all-in price at each poll. Kept in memory, so it starts over when the service restarts.
 */
export interface PriceHistory {
  /**
   * Wire-format version. Bump only for breaking changes.
   */
  schema_version: 1;
  game_id: string;
  series: PriceSeries[];
}
export interface PriceSeries {
  /**
   * The contract's key on the board, e.g. total-over-2.5.
   */
  key: string;
  points: PricePoint[];
}
export interface PricePoint {
  t: string;
  /**
   * The best all-in price then.
   */
  all_in: number;
  venue: Venue;
}
