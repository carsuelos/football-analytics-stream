// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

/**
 * On the engine's stream: drop everything received so far. What follows starts from scratch, after a new match, a seek, or a (re)connect.
 */
export interface MatchReset {
  /**
   * Wire-format version. Bump only for breaking changes.
   */
  schema_version: 1;
  /**
   * Goes up each time the engine starts a match over. 0 before the first match.
   */
  generation: number;
  match_id?: number;
}
