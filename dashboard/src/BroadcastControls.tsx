import type { Command } from './api'
import type { BroadcastStatus } from './schema/broadcast_status.schema'
import { buttonClass } from './ui'

const SPEEDS = [1, 10, 30, 60]

interface Props {
  status: BroadcastStatus | null
  disabled: boolean
  onCommand: (command: Command) => void
}

/**
 * Play/pause and speed for the simulator's broadcast. They need a loaded
 * match, so stay disabled until then. Seeking is the viewer's: the engine's DVR.
 */
export function BroadcastControls({ status, disabled, onCommand }: Props) {
  const off = disabled || status === null || status.state === 'idle'
  const playing = status?.state === 'playing'

  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        className={buttonClass}
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
            className={buttonClass}
            aria-pressed={status?.speed === speed}
            disabled={off}
            onClick={() => onCommand({ command: 'set_speed', speed })}
          >
            {speed}×
          </button>
        ))}
      </div>
    </div>
  )
}
