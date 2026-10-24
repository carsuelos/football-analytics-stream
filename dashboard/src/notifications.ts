import { useCallback, useEffect, useRef, useState } from 'react'
import { ALERT_NAMES } from './alerts'
import type { Alert } from './schema/alert.schema'
import type { EngineStatus, Team } from './schema/engine_status.schema'
import { matchClock } from './timeline'
import { useStoredFlag } from './useStored'

/**
 * How close (in match time) an alert must be to where the viewer is to count
 * as new. The engine sends the match so far on every connect and seek; those
 * alerts are history, not news.
 */
export const FRESH_S = 60

const supported = () => typeof Notification !== 'undefined'

/**
 * Whether to notify of alerts: the viewer's choice (remembered) and the
 * browser's permission, which turning it on asks for.
 */
export function useNotifySetting() {
  const [wanted, setWanted] = useStoredFlag('notify.alerts', false)
  const [permission, setPermission] = useState<NotificationPermission | 'unsupported'>(() => (supported() ? Notification.permission : 'unsupported'))
  const toggle = useCallback(async () => {
    if (wanted || !supported()) return setWanted(false)
    const granted = Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission
    setPermission(granted)
    if (granted === 'granted') setWanted(true)
  }, [wanted, setWanted])
  return { on: wanted && permission === 'granted', permission, toggle }
}

/** Whether new alerts ding: on by default, remembered. */
export function useSoundSetting() {
  return useStoredFlag('notify.sound', true)
}

/** A new alert, as the dashboard pops it up. */
export interface Toast {
  id: string
  alert: Alert
  title: string
  body: string
}

/** How long a pop-up stays, unless closed first. */
export const TOAST_MS = 10_000
/** The most pop-ups shown at once; older ones make way. */
export const MAX_TOASTS = 3

interface Settings {
  /** Mac (system) notifications, while the window is in the background. */
  system: boolean
  sound: boolean
}

/**
 * Announces each new alert: a pop-up in the dashboard, a ding (if sound is
 * on), and a system notification (on a Mac, in Notification Centre) when the
 * window is in the background and those are on. Each alert is announced at
 * most once while the page is open, so a reconnect or a rewatch doesn't
 * repeat it. `test` announces a sample, to try the settings.
 */
export function useAlertNotifications(settings: Settings, alerts: Alert[], status: EngineStatus | null, teams: Team[] | null) {
  const done = useRef(new Set<string>())
  const [toasts, setToasts] = useState<Toast[]>([])
  const dismiss = useCallback((id: string) => setToasts((ts) => ts.filter((t) => t.id !== id)), [])
  const { system, sound } = settings

  const announce = useCallback(
    (a: Alert, test = false) => {
      const team = teams?.find((t) => t.id === a.team_id)?.name
      const title = `${ALERT_NAMES[a.type]}${team ? ` · ${team}` : ''}`
      const body = `${matchClock(a)} · ${a.message.split('. By full time:')[0]}`
      const id = test ? `test-${Date.now()}` : a.id
      setToasts((ts) => [...ts.filter((t) => t.id !== id), { id, alert: a, title, body }].slice(-MAX_TOASTS))
      if (sound) ding()
      if (system && supported() && Notification.permission === 'granted' && (test || !document.hasFocus())) {
        const n = new Notification(title, { body, tag: id })
        n.onclick = () => {
          window.focus()
          n.close()
        }
      }
    },
    [teams, system, sound],
  )

  useEffect(() => {
    if (!status || status.state === 'rebuilding') return
    for (const a of alerts) {
      if (done.current.has(a.id) || !fresh(a, status)) continue
      done.current.add(a.id)
      announce(a)
    }
  }, [alerts, status, announce])

  const test = useCallback(() => announce(alerts.at(-1) ?? SAMPLE, true), [alerts, announce])
  return { toasts, dismiss, test }
}

/** What the test announces when the match has no alert yet. */
const SAMPLE: Alert = {
  schema_version: 1,
  id: 'sample',
  match_id: 0,
  offset: 0,
  period: 1,
  match_clock_s: 36 * 60 + 53,
  type: 'goal_chance',
  team_id: 0,
  value: 0.19,
  threshold: 0.18,
  window_s: 600,
  features: {},
  message: "A test: 19% chance to score in the next 10' (usually 13%)",
}

let audio: AudioContext | undefined

/**
 * A soft two-note chime, made on the spot (no sound file). Browsers only let
 * a page play sound after it's been clicked once, so the first alert after a
 * reload may be silent until then.
 */
export function ding() {
  try {
    audio ??= new AudioContext()
    const now = audio.currentTime
    for (const [i, freq] of [880, 1318.5].entries()) {
      const osc = audio.createOscillator()
      const gain = audio.createGain()
      osc.type = 'sine'
      osc.frequency.value = freq
      const start = now + i * 0.12
      gain.gain.setValueAtTime(0, start)
      gain.gain.linearRampToValueAtTime(0.18, start + 0.01)
      gain.gain.exponentialRampToValueAtTime(0.001, start + 0.6)
      osc.connect(gain).connect(audio.destination)
      osc.start(start)
      osc.stop(start + 0.65)
    }
  } catch {
    // No Web Audio (or blocked): the pop-up still shows.
  }
}

function fresh(a: Alert, status: EngineStatus) {
  if (status.period !== a.period || status.match_clock_s === undefined) return false
  const behind = status.match_clock_s - a.match_clock_s
  return behind >= -FRESH_S && behind <= FRESH_S
}
