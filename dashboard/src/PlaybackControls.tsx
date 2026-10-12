import { useState, type FormEvent } from 'react'
import type { Command } from './api'
import type { PlaybackStatus } from './schema/status.schema'

const SPEEDS = [1, 10, 30, 60]

/** The periods to seek to, with the minute each starts at on StatsBomb's match clock. */
const PERIODS = [
  { period: 1, label: '1st half', start: 0 },
  { period: 2, label: '2nd half', start: 45 },
  { period: 3, label: 'Extra time, 1st half', start: 90 },
  { period: 4, label: 'Extra time, 2nd half', start: 105 },
]

const button =
  'rounded-md bg-slate-800 px-3 py-1.5 text-sm hover:bg-slate-700 disabled:opacity-50 disabled:hover:bg-slate-800 aria-pressed:bg-sky-700'

interface Props {
  status: PlaybackStatus | null
  disabled: boolean
  onCommand: (command: Command) => void
}

/** Play/pause, speed and seek. They need a loaded match, so stay disabled until then. */
export function PlaybackControls({ status, disabled, onCommand }: Props) {
  const off = disabled || status === null || status.state === 'idle'
  const playing = status?.state === 'playing'

  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        className={button}
        disabled={off || status?.state === 'ended'}
        onClick={() => onCommand({ command: playing ? 'pause' : 'play' })}
      >
        {playing ? 'Pause' : 'Play'}
      </button>
      <div role="group" aria-label="Speed" className="flex gap-1">
        {SPEEDS.map((speed) => (
          <button
            key={speed}
            type="button"
            className={button}
            aria-pressed={status?.speed === speed}
            disabled={off}
            onClick={() => onCommand({ command: 'set_speed', speed })}
          >
            {speed}×
          </button>
        ))}
      </div>
      <SeekForm disabled={off} onSeek={(seek_to) => onCommand({ command: 'seek', seek_to })} />
    </div>
  )
}

interface SeekProps {
  disabled: boolean
  onSeek: (target: { period: number; match_clock_s: number }) => void
}

/**
 * Seeks to a minute within a period. StatsBomb's clock runs on across periods
 * (the 2nd half starts at 45:00) but stoppage time overlaps the next period,
 * so the period is chosen explicitly. Picking one moves the minute to its start.
 */
function SeekForm({ disabled, onSeek }: SeekProps) {
  const [period, setPeriod] = useState(1)
  const [minute, setMinute] = useState('0')

  // The input's required and min stop the form submitting an empty or negative minute.
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
          const p = PERIODS.find((p) => p.period === Number(e.target.value))!
          setPeriod(p.period)
          setMinute(String(p.start))
        }}
        className="rounded-md bg-slate-800 px-2 py-1.5 text-sm disabled:opacity-50"
      >
        {PERIODS.map((p) => (
          <option key={p.period} value={p.period}>
            {p.label}
          </option>
        ))}
      </select>
      <input
        aria-label="Minute"
        type="number"
        min={0}
        max={130}
        required
        value={minute}
        disabled={disabled}
        onChange={(e) => setMinute(e.target.value)}
        className="w-16 rounded-md bg-slate-800 px-2 py-1.5 text-sm disabled:opacity-50"
      />
      <button type="submit" className={button} disabled={disabled}>
        Go
      </button>
    </form>
  )
}
