// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.

export type LibraryDownloadState = "downloading" | "done" | "failed";

/**
 * The matches the simulator can download: every competition season in StatsBomb's open data, how many of its matches are already on disk, and the download in progress, if any. Served by the simulator (GET /library) through the engine (GET /api/library).
 */
export interface MatchLibrary {
  /**
   * Wire-format version. Bump only for breaking changes.
   */
  schema_version: 1;
  /**
   * Newest first.
   */
  seasons: LibrarySeason[];
  download?: LibraryDownload;
  /**
   * Why the list of seasons couldn't be refreshed from StatsBomb (the last one known is shown).
   */
  error?: string;
}
export interface LibrarySeason {
  competition_id: number;
  season_id: number;
  /**
   * e.g. UEFA Women's Euro.
   */
  competition: string;
  /**
   * e.g. 2025 or 2015/2016.
   */
  season: string;
  country?: string;
  gender: "male" | "female";
  youth?: boolean;
  /**
   * The goal and full-time models were trained on this season (every men's senior season from 2003, except the 2022 World Cup they're tested on), so its matches aren't a fair test of them.
   */
  in_training?: boolean;
  /**
   * Matches of this season on disk.
   */
  downloaded: number;
  /**
   * Matches StatsBomb has for it, once its list has been downloaded.
   */
  matches?: number;
}
export interface LibraryDownload {
  competition_id: number;
  season_id: number;
  competition: string;
  season: string;
  state: LibraryDownloadState;
  /**
   * Matches downloaded (or already on disk).
   */
  done: number;
  total: number;
  error?: string;
}
