// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

/**
 * Matches the simulator can replay (GET /matches).
 */
export interface MatchList {
  /**
   * Wire-format version. Bump only for breaking changes.
   */
  schema_version: 1;
  matches: MatchInfo[];
}
/**
 * A match without its events.
 */
export interface MatchInfo {
  match_id: number;
  competition: string;
  season: string;
  stage: string;
  /**
   * Kick-off date, YYYY-MM-DD.
   */
  date: string;
  home_team: Team;
  away_team: Team;
  home_score: number;
  away_score: number;
}
export interface Team {
  id: number;
  name: string;
}
