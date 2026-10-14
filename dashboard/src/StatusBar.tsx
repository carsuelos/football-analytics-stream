import type { Connection } from './matchState'
import type { EngineState, EngineStatus } from './schema/engine_status.schema'

const CONNECTION: Record<Connection, { text: string; dot: string }> = {
  connecting: { text: 'Connecting…', dot: 'bg-slate-500' },
  open: { text: 'Connected', dot: 'bg-emerald-400' },
  lost: { text: 'Reconnecting…', dot: 'bg-amber-400 animate-live' },
}

const STATE_NAMES: Record<EngineState, string> = {
  waiting: 'Waiting for a match',
  rebuilding: 'Catching up',
  live: 'Live',
  playing: 'Replaying',
  paused: 'Paused',
  ended: 'Ended',
}

interface Props {
  connection: Connection
  status: EngineStatus | null
}

/**
 * The stream's connection and the engine's state (the clock is on the
 * scoreboard). While the connection is lost the last state stays on screen, dimmed.
 */
export function StatusBar({ connection, status }: Props) {
  const { text, dot } = CONNECTION[connection]
  return (
    <p role="status" className="flex items-center gap-3 rounded-full border border-white/[0.06] bg-white/[0.03] px-3 py-1 text-xs">
      <span className="flex items-center gap-2 text-slate-400">
        <span className={`size-1.5 rounded-full ${dot}`} /> {text}
      </span>{' '}
      {status && (
        <span className={`font-medium text-slate-200 ${connection === 'lost' ? 'opacity-50' : ''}`}>{STATE_NAMES[status.state]}</span>
      )}
    </p>
  )
}
