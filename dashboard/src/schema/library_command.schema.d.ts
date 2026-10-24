// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

/**
 * Request body to download a competition season's matches into the simulator's data (POST /library through the engine's POST /api/library). One download at a time; matches already on disk are skipped.
 */
export interface LibraryCommand {
  /**
   * Wire-format version. Bump only for breaking changes.
   */
  schema_version: 1;
  competition_id: number;
  season_id: number;
}
