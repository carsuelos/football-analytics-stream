// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

/**
 * What happened. penalty_goal and penalty_missed are penalties in play; shootout_goal and shootout_miss are kicks in the shootout, which do not count as goals.
 */
export type IncidentKind =
  | "goal"
  | "own_goal"
  | "penalty_goal"
  | "penalty_missed"
  | "penalty_awarded"
  | "goal_disallowed"
  | "yellow_card"
  | "second_yellow"
  | "red_card"
  | "shootout_goal"
  | "shootout_miss";

/**
 * A key moment of the match (a goal, a card, a penalty), with the score after it. Derived by the engine from the event feed.
 */
export interface Incident {
  /**
   * Wire-format version. Bump only for breaking changes.
   */
  schema_version: 1;
  /**
   * Stable id: the same incident gets the same id when the match is replayed.
   */
  id: string;
  match_id: number;
  /**
   * Offset of the event the incident comes from.
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
   * Seconds of play when it happened, continuous across periods.
   */
  play_s: number;
  kind: IncidentKind;
  /**
   * The team it is for: the side that scored (for own_goal, the side the goal counts for), took the penalty, was awarded it, had the goal disallowed or was shown the card.
   */
  team_id: number;
  player?: Player;
  /**
   * The score after it, in the order of the teams.
   *
   * @minItems 2
   * @maxItems 2
   */
  score: [TeamScore, TeamScore];
  /**
   * On goal_disallowed: the id of the goal's incident.
   */
  cancels?: string;
  /**
   * On goal_disallowed: why it was disallowed.
   */
  reason?: "offside" | "foul" | "handball" | "other";
}
/**
 * The player who scored, took the penalty, gave it away (if the provider says) or was shown the card. For own_goal, the opponent who put the ball into his own net.
 */
export interface Player {
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
