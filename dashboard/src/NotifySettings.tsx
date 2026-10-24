import type { useNotifySetting } from './notifications'

const pill = 'flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-50'
const off = 'border-white/10 bg-white/[0.03] text-slate-400 hover:text-slate-200'
const on = 'border-sky-400/40 bg-sky-400/15 text-sky-200'

/**
 * How new alerts are announced. They always pop up on the dashboard; these
 * add a ding, and Mac notifications while the window is in the background.
 * Test announces the latest alert (or a sample) to try them.
 */
export function NotifySettings({
  system,
  sound,
  onSound,
  onTest,
}: {
  system: ReturnType<typeof useNotifySetting>
  sound: boolean
  onSound: (on: boolean) => void
  onTest: () => void
}) {
  const blocked = system.permission === 'denied'
  return (
    <div role="group" aria-label="Alert notifications" className="flex items-center gap-1.5">
      <button type="button" role="switch" aria-checked={sound} aria-label="Sound" onClick={() => onSound(!sound)} title={sound ? 'New alerts ding' : 'New alerts are silent'} className={`${pill} ${sound ? on : off}`}>
        <SpeakerIcon muted={!sound} />
      </button>
      {system.permission !== 'unsupported' && (
        <button
          type="button"
          role="switch"
          aria-checked={system.on}
          disabled={blocked}
          onClick={() => void system.toggle()}
          title={
            blocked
              ? "Notifications are blocked for this site in your browser's settings"
              : system.on
                ? 'New alerts also show as Mac notifications while this window is in the background'
                : 'Also show new alerts as Mac notifications while this window is in the background'
          }
          className={`${pill} ${system.on ? on : off}`}
        >
          <BellIcon off={!system.on} />
          {blocked ? 'Notifications blocked' : 'Notify me'}
        </button>
      )}
      <button type="button" onClick={onTest} title="Announce the latest alert (or a sample) to try these" className={`${pill} ${off}`}>
        Test
      </button>
    </div>
  )
}

function BellIcon({ off }: { off: boolean }) {
  return (
    <svg viewBox="0 0 24 24" className="size-3.5" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 8a6 6 0 1 1 12 0c0 7 3 8 3 8H3s3-1 3-8" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
      {off && <path d="M3 3l18 18" />}
    </svg>
  )
}

function SpeakerIcon({ muted }: { muted: boolean }) {
  return (
    <svg viewBox="0 0 24 24" className="size-3.5" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M11 5 6 9H2v6h4l5 4z" />
      {muted ? <path d="m22 9-6 6M16 9l6 6" /> : <path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14" />}
    </svg>
  )
}
