// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

/**
 * `play`, `pause` and `set_speed` act on the viewer's own playback; `seek` moves it to a point in the match up to the live edge (a later point goes live); `go_live` catches up with the broadcast and follows it.
 */
export type ViewerCommandType = "play" | "pause" | "set_speed" | "seek" | "go_live";

/**
 * Request body for the engine's playback control: the engine is a DVR over the broadcast.
 */
export interface ViewerCommand {
  /**
   * Wire-format version. Bump only for breaking changes.
   */
  schema_version: 1;
  command: ViewerCommandType;
  /**
   * Playback speed multiplier while behind live. Required for set_speed.
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
