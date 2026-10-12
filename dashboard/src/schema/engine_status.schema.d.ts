// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

/**
 * `waiting` for a match; `rebuilding` state from events that already happened (after a seek or a mid-match connect); `live`; or the match has `ended`.
 */
export type EngineState = "waiting" | "rebuilding" | "live" | "ended";

/**
 * Where the engine is in the match it is following.
 */
export interface EngineStatus {
  /**
   * Wire-format version. Bump only for breaking changes.
   */
  schema_version: 1;
  state: EngineState;
  /**
   * The generation of the last MatchReset.
   */
  generation: number;
  match_id?: number;
  /**
   * The teams seen so far, in order of first appearance.
   *
   * @maxItems 2
   */
  teams?: [] | [Team] | [Team, Team];
  /**
   * Period of the latest event processed.
   */
  period?: number;
  /**
   * Game clock of the latest event processed.
   */
  match_clock_s?: number;
  /**
   * Seconds of play so far, continuous across periods.
   */
  play_s?: number;
  /**
   * While `rebuilding`: the offset where live play resumes.
   */
  rebuilding_to?: number;
  /**
   * Events processed, in match-time order.
   */
  released: number;
  /**
   * Events held back for reordering.
   */
  buffered: number;
  /**
   * Events dropped for arriving too late to reorder.
   */
  late_dropped: number;
  /**
   * Duplicate events ignored.
   */
  duplicates: number;
}
export interface Team {
  id: number;
  name: string;
}
