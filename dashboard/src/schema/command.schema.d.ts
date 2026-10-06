// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

export type PlaybackCommandType = "load_match" | "play" | "pause" | "set_speed" | "seek";

/**
 * Request body for the simulator's HTTP control API.
 */
export interface PlaybackCommand {
  /**
   * Wire-format version. Bump only for breaking changes.
   */
  schema_version: 1;
  command: PlaybackCommandType;
  /**
   * Required for load_match.
   */
  match_id?: number;
  /**
   * Playback speed multiplier. Required for set_speed.
   */
  speed?: number;
  seek_to?: SeekTarget;
}
/**
 * Required for seek.
 */
export interface SeekTarget {
  /**
   * 1-2 regular halves, 3-4 extra time, 5 penalty shootout.
   */
  period: number;
  /**
   * Game clock in seconds (e.g. the second half starts at 2700). Clocks overlap across periods because of stoppage time, so always pair with period.
   */
  match_clock_s: number;
}
