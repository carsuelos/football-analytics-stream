import { useCallback, useEffect, useRef, useState } from 'react'
import { getMatches, getPlayback, sendCommand, type Command } from './api'
import type { EngineState } from './schema/engine_status.schema'
import type { MatchInfo } from './schema/match_list.schema'
import type { PlaybackStatus } from './schema/status.schema'

export interface Playback {
  /** The matches the simulator can play, or null until they have been fetched. */
  matches: MatchInfo[] | null
  status: PlaybackStatus | null
  /** The last request's error, cleared by the next success. */
  error: string | null
  /** Whether a command is in flight; controls are disabled meanwhile. */
  pending: boolean
  send: (command: Command) => Promise<void>
}

/**
 * Tracks the simulator's playback through the engine. The status comes from
 * each command's reply, plus a fetch on load and whenever the engine's state
 * changes, which catches what no command reports: the match ending on its
 * own, or the engine coming back after being down.
 */
export function usePlayback(engineState?: EngineState): Playback {
  const [matches, setMatches] = useState<MatchInfo[] | null>(null)
  const [status, setStatus] = useState<PlaybackStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [inFlight, setInFlight] = useState(0)
  // Replies can arrive out of order (e.g. a slow fetch after a quick command),
  // so only the latest request may update the status.
  const latest = useRef(0)

  const track = useCallback((request: Promise<PlaybackStatus>) => {
    const id = ++latest.current
    return request.then(
      (reply) => {
        if (id === latest.current) {
          setStatus(reply)
          setError(null)
        }
      },
      (e: unknown) => {
        if (id === latest.current) {
          setError(messageOf(e))
        }
      },
    )
  }, [])

  useEffect(() => {
    void track(getPlayback())
  }, [engineState, track])

  const loaded = matches !== null
  useEffect(() => {
    if (!loaded) {
      getMatches().then(
        (list) => setMatches(list.matches),
        (e: unknown) => setError(messageOf(e)),
      )
    }
  }, [engineState, loaded])

  const send = useCallback(
    async (command: Command) => {
      setInFlight((n) => n + 1)
      try {
        await track(sendCommand(command))
      } finally {
        setInFlight((n) => n - 1)
      }
    },
    [track],
  )

  return { matches, status, error, pending: inFlight > 0, send }
}

const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e))
