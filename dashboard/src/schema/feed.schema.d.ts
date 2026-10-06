// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

export type FeedMessageKind = "event" | "match_start" | "reset" | "match_end";
export type EventType =
  | "pass"
  | "carry"
  | "shot"
  | "ball_receipt"
  | "ball_recovery"
  | "interception"
  | "duel"
  | "dribble"
  | "dribbled_past"
  | "clearance"
  | "block"
  | "pressure"
  | "foul_committed"
  | "foul_won"
  | "miscontrol"
  | "dispossessed"
  | "goalkeeper"
  | "fifty_fifty"
  | "offside"
  | "substitution"
  | "half_start"
  | "half_end"
  | "other";
/**
 * Pitch coordinates [x, y] on a 120x80 pitch, oriented so the acting team attacks towards x = 120.
 *
 * @minItems 2
 * @maxItems 2
 */
export type Point = [number, number];
/**
 * Success or failure for actions that have one (e.g. pass completion). Omitted otherwise.
 */
export type EventOutcome = "success" | "failure";
export type ShotOutcome = "goal" | "saved" | "blocked" | "off_target" | "post" | "other";

/**
 * One WebSocket message on the simulator feed. `kind` says which payload field is set.
 */
export interface FeedMessage {
  /**
   * Wire-format version. Bump only for breaking changes.
   */
  schema_version: 1;
  kind: FeedMessageKind;
  event?: MatchEvent;
  marker?: FeedMarker;
}
/**
 * A single normalized match event. Raw provider data never crosses the simulator boundary.
 */
export interface MatchEvent {
  /**
   * Wire-format version. Bump only for breaking changes.
   */
  schema_version: 1;
  /**
   * Stable unique event id (used for de-duplication).
   */
  id: string;
  match_id: number;
  /**
   * Per-match sequence number of an event in the feed, starting at 0.
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
  type: EventType;
  team: Team;
  /**
   * Possession sequence number within the match.
   */
  possession_id: number;
  possession_team_id: number;
  player?: Player;
  location?: Point;
  end_location?: Point;
  outcome?: EventOutcome;
  shot?: ShotDetail;
}
export interface Team {
  id: number;
  name: string;
}
export interface Player {
  id: number;
  name: string;
}
export interface ShotDetail {
  xg: number;
  outcome: ShotOutcome;
}
/**
 * Stream position for non-event messages. On `reset`, consumers drop state and rebuild up to this position.
 */
export interface FeedMarker {
  match_id: number;
  /**
   * Per-match sequence number of an event in the feed, starting at 0.
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
}
