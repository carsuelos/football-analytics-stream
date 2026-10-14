// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

export type FeedMessageKind = "event" | "match_start" | "match_end";
/**
 * What happened. For own_goal, team and player are the side that put the ball into its own net; the goal counts for the opponent. goal_disallowed cancels a goal already in the feed (e.g. after a VAR review): team is the side whose goal it was, and disallowed_goal says which and why.
 */
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
  | "own_goal"
  | "goal_disallowed"
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
 * The situation the shot came from. Omitted if the provider does not say.
 */
export type ShotType = "open_play" | "free_kick" | "corner" | "penalty" | "kick_off";
/**
 * A card shown to player with this event: on a foul_committed, or on other for misconduct away from a foul. second_yellow is a sending-off, like red.
 */
export type Card = "yellow" | "second_yellow" | "red";

/**
 * One message on the event feed. `kind` says which payload field is set. `match_start` comes first when a subscriber syncs and whenever a new match is loaded; then the match's events in offset order; then `match_end` after the last one.
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
  card?: Card;
  /**
   * On foul_committed or foul_won: the foul gave away a penalty. A provider may flag both events of the same foul.
   */
  penalty_awarded?: boolean;
  disallowed_goal?: DisallowedGoal;
}
export interface Team {
  id: number;
  name: string;
}
export interface Player {
  id: number;
  /**
   * The name to show: the provider's short name (e.g. Lionel Messi) if it has one.
   */
  name: string;
}
export interface ShotDetail {
  xg: number;
  outcome: ShotOutcome;
  type?: ShotType;
}
/**
 * On goal_disallowed: the goal it cancels.
 */
export interface DisallowedGoal {
  /**
   * id of the shot or own_goal event of the goal.
   */
  event_id: string;
  /**
   * Why a goal was disallowed.
   */
  reason: "offside" | "foul" | "handball" | "other";
}
/**
 * Stream position for non-event messages.
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
  /**
   * Per-match sequence number of an event in the feed, starting at 0.
   */
  head?: number;
}
