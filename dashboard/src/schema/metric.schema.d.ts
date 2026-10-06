// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

/**
 * Rolling-window metrics for both teams at a point in match time.
 */
export interface MetricSnapshot {
  /**
   * Wire-format version. Bump only for breaking changes.
   */
  schema_version: 1;
  match_id: number;
  /**
   * Offset of the last event included.
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
   * Window length in match seconds (e.g. 300 or 600).
   */
  window_s: number;
  /**
   * @minItems 2
   * @maxItems 2
   */
  teams: [TeamMetrics, TeamMetrics];
}
export interface TeamMetrics {
  team_id: number;
  /**
   * Share of attacking-third touches in the window (0-1).
   */
  field_tilt: number;
  xt_added: number;
  /**
   * xT added per match minute.
   */
  xt_velocity: number;
  pressure_index: number;
}
