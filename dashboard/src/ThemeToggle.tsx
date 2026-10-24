import { useEffect } from 'react'
import { useStoredFlag } from './useStoredFlag'

/** Where the choice is kept; index.html reads it too, to paint the right theme first. */
export const THEME_KEY = 'theme.light'

/** A small switch between the dark theme (the default) and the light one. */
export function ThemeToggle() {
  const [light, setLight] = useStoredFlag(THEME_KEY, false)
  useEffect(() => {
    document.documentElement.classList.toggle('light', light)
  }, [light])
  return (
    <button
      type="button"
      role="switch"
      aria-checked={light}
      aria-label="Light theme"
      title={light ? 'Switch to the dark theme' : 'Switch to the light theme'}
      onClick={() => setLight(!light)}
      className="grid size-8 place-items-center rounded-lg border border-white/[0.06] text-slate-400 transition hover:bg-white/[0.05] hover:text-slate-100"
    >
      {light ? <MoonIcon /> : <SunIcon />}
    </button>
  )
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-4" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-4" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" />
    </svg>
  )
}
