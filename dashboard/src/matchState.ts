import type { Alert } from './schema/alert.schema'
import type { EngineStatus } from './schema/engine_status.schema'
import type { Incident } from './schema/incident.schema'
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
  /** Goals, cards, penalties and the shootout, in the order they happened. */
  incidents: Incident[]
}

/** A message on the stream (named like its SSE event), or a change in the connection. */
export type StreamEvent =
  | { type: 'reset'; data: MatchReset }
  | { type: 'status'; data: EngineStatus }
  | { type: 'snapshot'; data: MetricSnapshot }
  | { type: 'alert'; data: Alert }
  | { type: 'incident'; data: Incident }
  | { type: 'open' }
  | { type: 'lost' }

/** Several stream events applied in one go, so a backlog renders once rather than once per message. */
export type StreamAction = StreamEvent | { type: 'batch'; events: StreamEvent[] }

export const initialMatchState: MatchState = {
  connection: 'connecting',
  reset: null,
  status: null,
  snapshots: [],
  alerts: [],
  incidents: [],
}

/**
 * Applies one stream event. The stream always starts with a reset, then the
 * latest status and the history, so a reset (on a new match, a seek, or a
 * reconnect) clears everything and the history rebuilds it.
 */
export function matchReducer(state: MatchState, event: StreamAction): MatchState {
  switch (event.type) {
    case 'batch':
      return applyBatch(state, event.events)
    case 'open':
      return { ...state, connection: 'open' }
    case 'lost':
      return { ...state, connection: 'lost' }
    case 'reset':
      return { ...state, reset: event.data, status: null, snapshots: [], alerts: [], incidents: [] }
    case 'status':
      return { ...state, status: event.data }
    case 'snapshot':
      return { ...state, snapshots: [...state.snapshots, event.data] }
    case 'alert':
      return { ...state, alerts: [...state.alerts, event.data] }
    case 'incident':
      return { ...state, incidents: [...state.incidents, event.data] }
  }
}

/**
 * The same as applying each event in turn, but each history list is copied
 * once per batch rather than once per event: a reconnect's backlog is a whole
 * match, thousands of snapshots.
 */
function applyBatch(state: MatchState, events: StreamEvent[]): MatchState {
  let next = { ...state, snapshots: [...state.snapshots], alerts: [...state.alerts], incidents: [...state.incidents] }
  for (const event of events) {
    switch (event.type) {
      case 'snapshot':
        next.snapshots.push(event.data)
        break
      case 'alert':
        next.alerts.push(event.data)
        break
      case 'incident':
        next.incidents.push(event.data)
        break
      default:
        next = matchReducer(next, event)
        // A reset empties the lists; give the rest of the batch its own copies.
        next = { ...next, snapshots: [...next.snapshots], alerts: [...next.alerts], incidents: [...next.incidents] }
    }
  }
  return next
}
