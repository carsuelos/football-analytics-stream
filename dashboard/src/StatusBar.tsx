import type { Connection } from './matchState'
import type { EngineState, EngineStatus } from './schema/engine_status.schema'
import { matchMinute, periodName } from './timeline'

const CONNECTION: Record<Connection, { text: string; dot: string }> = {
  connecting: { text: 'Connecting…', dot: 'bg-slate-500' },
  open: { text: 'Connected', dot: 'bg-emerald-500' },
  lost: { text: 'Reconnecting…', dot: 'bg-amber-500' },
}

const STATE_NAMES: Record<EngineState, string> = {
  waiting: 'Waiting for a match',
  rebuilding: 'Catching up',
  live: 'Live',
  ended: 'Ended',
}

interface Props {
  connection: Connection
  status: EngineStatus | null
}

/**
 * The stream's connection, the engine's state and the match clock. While the
 * connection is lost the last state stays on screen, dimmed.
 */
export function StatusBar({ connection, status }: Props) {
  const { text, dot } = CONNECTION[connection]
  const { period, match_clock_s } = status ?? {}
  const clock =
    period === undefined || match_clock_s === undefined
      ? null
      : period === 5
        ? periodName(period)
        : `${matchMinute({ period, match_clock_s })} · ${periodName(period)}`

  return (
    <div className="flex items-center gap-4 text-sm">
      <p role="status" className="flex items-center gap-4">
        <span className="flex items-center gap-2 text-slate-400">
          <span className={`size-2 rounded-full ${dot}`} /> {text}
        </span>{' '}
        {status && <span className={connection === 'lost' ? 'opacity-50' : ''}>{STATE_NAMES[status.state]}</span>}
      </p>
      {clock && (
        <p className={`font-semibold tabular-nums ${connection === 'lost' ? 'opacity-50' : ''}`}>
          <span className="sr-only">Match clock: </span>
          {clock}
        </p>
      )}
    </div>
  )
}
