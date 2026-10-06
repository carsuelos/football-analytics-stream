// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

export type AlertType = "momentum_shift" | "goal_threat" | "control_shift";

/**
 * A tactical alert raised by a detector.
 */
export interface Alert {
  /**
   * Wire-format version. Bump only for breaking changes.
   */
  schema_version: 1;
  id: string;
  match_id: number;
  /**
   * Offset of the event that triggered the alert.
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
  type: AlertType;
  team_id: number;
  /**
   * Detector output (e.g. z-score or heuristic goal score).
   */
  value: number;
  threshold: number;
  window_s: number;
  /**
   * Inputs that contributed to the alert, by name.
   */
  features: {
    [k: string]: number;
  };
  message: string;
}
