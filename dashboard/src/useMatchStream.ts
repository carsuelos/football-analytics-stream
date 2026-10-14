import { useEffect, useReducer } from 'react'
import { initialMatchState, matchReducer, type MatchState, type StreamEvent } from './matchState'

/** How long to wait before reconnecting after the stream was refused. */
export const RETRY_MS = 2000

/**
 * Messages are applied together at most this often. On (re)connecting the
 * engine sends the whole match so far, thousands of messages at once; applying
 * them one by one would redraw the charts for each.
 */
export const FLUSH_MS = 50

const MESSAGE_TYPES = ['reset', 'status', 'snapshot', 'alert', 'incident'] as const

/** Follows the engine's match stream and returns the match state built from it. */
export function useMatchStream(url = '/api/stream'): MatchState {
  const [state, dispatch] = useReducer(matchReducer, initialMatchState)

  useEffect(() => {
    let source: EventSource | undefined
    let retry: ReturnType<typeof setTimeout> | undefined
    let flushTimer: ReturnType<typeof setTimeout> | undefined
    let pending: StreamEvent[] = []

    const flush = () => {
      clearTimeout(flushTimer)
      flushTimer = undefined
      if (pending.length) {
        dispatch({ type: 'batch', events: pending })
        pending = []
      }
    }
    const queue = (event: StreamEvent) => {
      pending.push(event)
      flushTimer ??= setTimeout(flush, FLUSH_MS)
    }

    const connect = () => {
      const es = new EventSource(url)
      source = es
      es.onopen = () => {
        flush()
        dispatch({ type: 'open' })
      }
      es.onerror = () => {
        flush()
        dispatch({ type: 'lost' })
        // EventSource reconnects by itself when a connection drops, but gives
        // up on an error reply (e.g. the dev proxy's 5xx while the engine is
        // down), so then retry ourselves.
        if (es.readyState === EventSource.CLOSED) {
          retry = setTimeout(connect, RETRY_MS)
        }
      }
      for (const type of MESSAGE_TYPES) {
        es.addEventListener(type, (e) => queue({ type, data: JSON.parse(e.data) } as StreamEvent))
      }
    }

    connect()
    return () => {
      clearTimeout(retry)
      clearTimeout(flushTimer)
      source?.close()
    }
  }, [url])

  return state
}
