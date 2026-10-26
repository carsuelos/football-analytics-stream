// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

/**
 * `waiting` for a match; `rebuilding` state from events that already happened (after a seek or a mid-match connect); `live`, following the broadcast as it happens; `playing` behind live, at the viewer's speed; `paused`; or the viewer has reached the end of the match (`ended`).
 */
export type EngineState = "waiting" | "rebuilding" | "live" | "playing" | "paused" | "ended";

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
   * The score as of the latest event processed, in the order of teams.
   *
   * @maxItems 2
   */
  score?: [] | [TeamScore] | [TeamScore, TeamScore];
  /**
   * Period of the latest event processed: where the viewer is.
   */
  period?: number;
  /**
   * Game clock of the latest event processed.
   */
  match_clock_s?: number;
  /**
   * Whether the period of the latest event has ended (half-time, full time, or the end of a period of extra time): the clock stands still until the next one kicks off. Between events it otherwise runs on.
   */
  period_over?: boolean;
  /**
   * Seconds of play so far, continuous across periods.
   */
  play_s?: number;
  /**
   * The viewer's playback speed while behind live.
   */
  speed?: number;
  live_edge?: LiveEdge;
  /**
   * Seconds of play between the viewer and the live edge.
   */
  behind_live_s?: number;
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
/**
 * One team's score. Goals exclude the penalty shootout, which has its own count.
 */
export interface TeamScore {
  team_id: number;
  goals: number;
  /**
   * Penalties scored in the shootout, once it has started.
   */
  shootout?: number;
}
/**
 * The latest point of the broadcast received so far: the viewer can seek up to here.
 */
export interface LiveEdge {
  /**
   * Events received so far.
   */
  offset: number;
  /**
   * 1-2 regular halves, 3-4 extra time, 5 penalty shootout.
   */
  period: number;
  /**
   * Game clock in seconds (e.g. the second half starts at 2700). Clocks overlap across periods because of stoppage time, so always pair with period.
   */
  match_clock_s: number;
  /**
   * Seconds of play up to the live edge, continuous across periods.
   */
  play_s: number;
}
