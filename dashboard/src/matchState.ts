import type { Alert } from './schema/alert.schema'
import type { EngineStatus } from './schema/engine_status.schema'
import type { MatchReset } from './schema/match_reset.schema'
import type { MetricSnapshot } from './schema/metric.schema'

/** Whether the stream is connected. While it is lost, the last match state stays on screen. */
export type Connection = 'connecting' | 'open' | 'lost'

/** The engine's view of the current match, as built from its stream. */
export interface MatchState {
  connection: Connection
  reset: MatchReset | null
  status: EngineStatus | null
  snapshots: MetricSnapshot[]
  alerts: Alert[]
}

/** A message on the stream (named like its SSE event), or a change in the connection. */
export type StreamEvent =
  | { type: 'reset'; data: MatchReset }
  | { type: 'status'; data: EngineStatus }
  | { type: 'snapshot'; data: MetricSnapshot }
  | { type: 'alert'; data: Alert }
  | { type: 'open' }
  | { type: 'lost' }

export const initialMatchState: MatchState = {
  connection: 'connecting',
  reset: null,
  status: null,
  snapshots: [],
  alerts: [],
}

/**
 * Applies one stream event. The stream always starts with a reset, then the
 * latest status and the history, so a reset (on a new match, a seek, or a
 * reconnect) clears everything and the history rebuilds it.
 */
export function matchReducer(state: MatchState, event: StreamEvent): MatchState {
  switch (event.type) {
    case 'open':
      return { ...state, connection: 'open' }
    case 'lost':
      return { ...state, connection: 'lost' }
    case 'reset':
      return { ...state, reset: event.data, status: null, snapshots: [], alerts: [] }
    case 'status':
      return { ...state, status: event.data }
    case 'snapshot':
      return { ...state, snapshots: [...state.snapshots, event.data] }
    case 'alert':
      return { ...state, alerts: [...state.alerts, event.data] }
  }
}
