import type { BroadcastCommand } from './schema/broadcast_command.schema'
import type { BroadcastStatus } from './schema/broadcast_status.schema'
import type { EngineStatus } from './schema/engine_status.schema'
import type { MatchLibrary } from './schema/match_library.schema'
import type { MatchList } from './schema/match_list.schema'
import type { ViewerCommand } from './schema/viewer_command.schema'

/** An error from the engine API: its message, and the HTTP status (0 if the engine was unreachable). */
export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** A broadcast command; schema_version is added when it is sent. */
export type BroadcastAction = Omit<BroadcastCommand, 'schema_version'>

export const getMatches = () => request<MatchList>('/matches')

export const getBroadcast = () => request<BroadcastStatus>('/broadcast')

/** The matches the simulator can download from StatsBomb's open data, and its download's progress. */
export const getLibrary = () => request<MatchLibrary>('/library')

/** Has the simulator download a competition season's matches (in the background). */
export const downloadSeason = (competition_id: number, season_id: number) => post<MatchLibrary>('/library', { competition_id, season_id })

/** Sends a broadcast command to the simulator (through the engine) and returns the new broadcast status. */
export const sendBroadcast = (command: BroadcastAction) => post<BroadcastStatus>('/broadcast', command)

/** A viewer command; schema_version is added when it is sent. */
export type ViewerAction = Omit<ViewerCommand, 'schema_version'>

/** Sends a viewer command to the engine's DVR and returns the engine's new status. */
export const sendViewer = (command: ViewerAction) => post<EngineStatus>('/control', command)

const post = <T>(path: string, command: object) =>
  request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ schema_version: 1, ...command }),
  })

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, init)
  } catch {
    throw new ApiError('engine unavailable', 0)
  }
  const body: unknown = await res.json().catch(() => undefined)
  if (res.ok && body !== undefined) {
    return body as T
  }
  if (isErrorBody(body)) {
    throw new ApiError(body.error, res.status)
  }
  // Without the engine's {"error": ...} body, the reply came from something in
  // between, e.g. the dev proxy answering 5xx because the engine is down.
  throw new ApiError(res.status >= 500 ? 'engine unavailable' : `unexpected reply (HTTP ${res.status})`, res.status)
}

function isErrorBody(body: unknown): body is { error: string } {
  return typeof body === 'object' && body !== null && typeof (body as { error?: unknown }).error === 'string'
}
