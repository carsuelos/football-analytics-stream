import { useState, type FormEvent } from 'react'
import type { ViewerAction } from './api'
import type { EngineStatus, LiveEdge } from './schema/engine_status.schema'
import { duration, matchMinute, periodName } from './timeline'
import { buttonClass } from './ui'

const SPEEDS = [1, 10, 30, 60]

/** The periods to seek to, with the minute each starts at on StatsBomb's match clock. */
const PERIOD_STARTS: Record<number, number> = { 1: 0, 2: 45, 3: 90, 4: 105 }

interface Props {
  status: EngineStatus | null
  disabled: boolean
  onCommand: (command: ViewerAction) => void
}

/**
 * The viewer's controls on the engine's DVR: how far behind the broadcast it
 * is, play/pause, go live, its own speed, and seeking up to the live edge.
 * They need a match to have arrived, so stay disabled until then.
 */
export function ViewerControls({ status, disabled, onCommand }: Props) {
  const state = status?.state
  const edge = status?.live_edge
  const off = disabled || edge === undefined
  const behind = status?.behind_live_s ?? 0
  // While rebuilding after a seek, the viewer plays on unless it was paused.
  const playing = state === 'live' || state === 'playing' || state === 'rebuilding'
  const canGoLive = state === 'paused' || state === 'playing' || (state === 'rebuilding' && behind > 0)

  return (
    <div className="flex flex-wrap items-center gap-3">
      <LiveIndicator state={state} behind={behind} />
      <button
        type="button"
        className={buttonClass}
        disabled={off || state === 'ended'}
        onClick={() => onCommand({ command: playing ? 'pause' : 'play' })}
      >
        {playing ? 'Pause' : 'Play'}
      </button>
      <button type="button" className={buttonClass} disabled={off || !canGoLive} onClick={() => onCommand({ command: 'go_live' })}>
        Go live
      </button>
      <div role="group" aria-label="Speed" className="flex gap-1">
        {SPEEDS.map((speed) => (
          <button
            key={speed}
            type="button"
            className={buttonClass}
            aria-pressed={status?.speed === speed}
            disabled={off}
            onClick={() => onCommand({ command: 'set_speed', speed })}
          >
            {speed}×
          </button>
        ))}
      </div>
      <SeekForm edge={edge} disabled={off} onSeek={(seek_to) => onCommand({ command: 'seek', seek_to })} />
    </div>
  )
}

function LiveIndicator({ state, behind }: { state?: EngineStatus['state']; behind: number }) {
  if (state === 'live') {
    return (
      <span className="flex items-center gap-1.5 text-sm font-semibold text-red-400">
        <span className="size-2 rounded-full bg-red-500" /> LIVE
      </span>
    )
  }
  if (behind > 0) {
    return <span className="text-sm tabular-nums text-amber-300">{duration(behind)} behind live</span>
  }
  return null
}

interface SeekProps {
  edge?: LiveEdge
  disabled: boolean
  onSeek: (target: { period: number; match_clock_s: number }) => void
}

/**
 * Seeks to a minute within a period, up to the live edge. StatsBomb's clock
 * runs on across periods (the 2nd half starts at 45:00) but stoppage time
 * overlaps the next period, so the period is chosen explicitly. Picking one
 * moves the minute to its start. A minute past the live edge goes live.
 */
function SeekForm({ edge, disabled, onSeek }: SeekProps) {
  const [chosen, setChosen] = useState(1)
  const [minute, setMinute] = useState('0')
  const periods = Object.keys(PERIOD_STARTS)
    .map(Number)
    .filter((p) => p <= (edge?.period ?? 1))
  // A new match can start the edge in an earlier period than the one chosen.
  const period = Math.min(chosen, periods[periods.length - 1])
  const max = edge?.period === period ? Math.floor(edge.match_clock_s / 60) : undefined

  // The input's required, min and max stop the form submitting a minute out of range.
  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSeek({ period, match_clock_s: Number(minute) * 60 })
  }

  return (
    <form aria-label="Seek" className="flex items-center gap-2" onSubmit={submit}>
      <select
        aria-label="Period"
        value={period}
        disabled={disabled}
        onChange={(e) => {
          const p = Number(e.target.value)
          setChosen(p)
          setMinute(String(PERIOD_STARTS[p]))
        }}
        className="rounded-md bg-slate-800 px-2 py-1.5 text-sm disabled:opacity-50"
      >
        {periods.map((p) => (
          <option key={p} value={p}>
            {periodName(p)}
          </option>
        ))}
      </select>
      <input
        aria-label="Minute"
        type="number"
        min={0}
        max={max ?? 130}
        required
        value={minute}
        disabled={disabled}
        onChange={(e) => setMinute(e.target.value)}
        className="w-16 rounded-md bg-slate-800 px-2 py-1.5 text-sm disabled:opacity-50"
      />
      <button type="submit" className={buttonClass} disabled={disabled}>
        Go
      </button>
      {edge && <span className="text-xs text-slate-400">Live: {matchMinute(edge)}</span>}
    </form>
  )
}
