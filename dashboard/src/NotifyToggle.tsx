import type { useNotifySetting } from './notifications'

/** The bell that turns alert notifications on and off. */
export function NotifyToggle({ setting }: { setting: ReturnType<typeof useNotifySetting> }) {
  const { on, permission, toggle } = setting
  if (permission === 'unsupported') return null
  const blocked = permission === 'denied'
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      disabled={blocked}
      onClick={() => void toggle()}
      title={
        blocked
          ? "Notifications are blocked for this site in your browser's settings"
          : on
            ? 'Alerts show as notifications while this window is in the background'
            : 'Show new alerts as notifications'
      }
      className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${
        on ? 'border-sky-400/40 bg-sky-400/15 text-sky-200' : 'border-white/10 bg-white/[0.03] text-slate-400 hover:text-slate-200'
      }`}
    >
      <BellIcon off={!on} />
      {blocked ? 'Notifications blocked' : 'Notify me'}
    </button>
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
