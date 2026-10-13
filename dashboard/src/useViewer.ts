import { useCallback, useState } from 'react'
import { sendViewer, type ViewerAction } from './api'

export interface Viewer {
  /** The last command's error, cleared by the next success. */
  error: string | null
  /** Whether a command is in flight; controls are disabled meanwhile. */
  pending: boolean
  send: (command: ViewerAction) => Promise<void>
}

/**
 * Sends the viewer's commands to the engine's DVR. Their effect, the engine's
 * new status, arrives on the match stream like every other status change.
 */
export function useViewer(): Viewer {
  const [error, setError] = useState<string | null>(null)
  const [inFlight, setInFlight] = useState(0)

  const send = useCallback(async (command: ViewerAction) => {
    setInFlight((n) => n + 1)
    try {
      await sendViewer(command)
      setError(null)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setInFlight((n) => n - 1)
    }
  }, [])

  return { error, pending: inFlight > 0, send }
}
