import type { PlaybackCommand } from './schema/command.schema'
import type { MatchList } from './schema/match_list.schema'
import type { PlaybackStatus } from './schema/status.schema'

/** An error from the engine API: its message, and the HTTP status (0 if the engine was unreachable). */
export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** A playback command; schema_version is added when it is sent. */
export type Command = Omit<PlaybackCommand, 'schema_version'>

export const getMatches = () => request<MatchList>('/matches')

export const getPlayback = () => request<PlaybackStatus>('/playback')

/** Sends a playback command to the simulator (through the engine) and returns the new playback status. */
export const sendCommand = (command: Command) =>
  request<PlaybackStatus>('/control', {
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
