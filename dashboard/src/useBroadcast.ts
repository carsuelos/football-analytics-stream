import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getMatches, getBroadcast, sendBroadcast, type BroadcastAction } from './api'
import type { EngineState } from './schema/engine_status.schema'
import type { MatchInfo } from './schema/match_list.schema'
import type { BroadcastStatus } from './schema/broadcast_status.schema'

export interface Broadcast {
  /**
   * Whether there is a simulator to control: false when the engine says it has
   * none (a feed nobody here controls, like a real one), null until known.
   */
  controllable: boolean | null
  /** The matches the simulator can play, or null until they have been fetched. */
  matches: MatchInfo[] | null
  status: BroadcastStatus | null
  /** The last request's error, cleared by the next success. */
  error: string | null
  /** Whether a command is in flight; controls are disabled meanwhile. */
  pending: boolean
  /** Sends a command; resolves to whether it succeeded (a failure sets error). */
  send: (command: BroadcastAction) => Promise<boolean>
  /** Fetches the match list again, e.g. after downloading more. */
  refreshMatches: () => void
}

/**
 * Tracks the simulator's broadcast through the engine. The status comes from
 * each command's reply, plus a fetch on load and whenever the engine's state
 * changes, which catches what no command reports: the match ending on its
 * own, or the engine coming back after being down.
 *
 * An engine with no simulator answers 404 to the broadcast endpoints; that
 * makes controllable false rather than an error.
 */
export function useBroadcast(engineState?: EngineState): Broadcast {
  const [matches, setMatches] = useState<MatchInfo[] | null>(null)
  const [status, setStatus] = useState<BroadcastStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [controllable, setControllable] = useState<boolean | null>(null)
  const [inFlight, setInFlight] = useState(0)
  // Replies can arrive out of order (e.g. a slow fetch after a quick command),
  // so only the latest request may update the status.
  const latest = useRef(0)

  const track = useCallback((request: Promise<BroadcastStatus>, { probe = false } = {}) => {
    const id = ++latest.current
    return request.then(
      (reply) => {
        if (id === latest.current) {
          setStatus(reply)
          setError(null)
          setControllable(true)
        }
        return true
      },
      (e: unknown) => {
        if (id === latest.current) {
          // Only a fetch can tell: a command's 404 is a missing match.
          if (probe && noSimulator(e)) {
            setStatus(null)
            setError(null)
            setControllable(false)
          } else {
            setError(messageOf(e))
          }
        }
        return false
      },
    )
  }, [])

  useEffect(() => {
    void track(getBroadcast(), { probe: true })
  }, [engineState, track])

  const loadMatches = useCallback(
    () =>
      getMatches().then(
        (list) => setMatches(list.matches),
        (e: unknown) => (noSimulator(e) ? setControllable(false) : setError(messageOf(e))),
      ),
    [],
  )
  const loaded = matches !== null
  useEffect(() => {
    if (!loaded) void loadMatches()
  }, [engineState, loaded, loadMatches])

  const send = useCallback(
    async (command: BroadcastAction) => {
      setInFlight((n) => n + 1)
      try {
        return await track(sendBroadcast(command))
      } finally {
        setInFlight((n) => n - 1)
      }
    },
    [track],
  )

  const refreshMatches = useCallback(() => void loadMatches(), [loadMatches])

  return { controllable, matches, status, error, pending: inFlight > 0, send, refreshMatches }
}

const noSimulator = (e: unknown) => e instanceof ApiError && e.status === 404

const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e))
