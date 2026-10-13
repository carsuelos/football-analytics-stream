// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

/**
 * `load_match` replaces the broadcast with a match, ready to kick off; `play` and `pause` start and hold the broadcast; `set_speed` sets how fast match time passes.
 */
export type BroadcastCommandType = "load_match" | "play" | "pause" | "set_speed";

/**
 * Request body for the simulator's HTTP control API. The simulator is a broadcaster: it publishes the loaded match once, in order, and never seeks. Viewers rewind and seek on their side (see ViewerCommand).
 */
export interface BroadcastCommand {
  /**
   * Wire-format version. Bump only for breaking changes.
   */
  schema_version: 1;
  command: BroadcastCommandType;
  /**
   * Required for load_match.
   */
  match_id?: number;
  /**
   * Broadcast speed multiplier. Required for set_speed.
   */
  speed?: number;
}
