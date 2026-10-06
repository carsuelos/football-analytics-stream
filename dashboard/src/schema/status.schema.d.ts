// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

export type PlaybackState = "idle" | "playing" | "paused" | "ended";

/**
 * Current simulator playback state.
 */
export interface PlaybackStatus {
  /**
   * Wire-format version. Bump only for breaking changes.
   */
  schema_version: 1;
  state: PlaybackState;
  speed: number;
  match_id?: number;
  /**
   * Next offset to be emitted.
   */
  offset?: number;
  /**
   * 1-2 regular halves, 3-4 extra time, 5 penalty shootout.
   */
  period?: number;
  /**
   * Game clock in seconds (e.g. the second half starts at 2700). Clocks overlap across periods because of stoppage time, so always pair with period.
   */
  match_clock_s?: number;
}
