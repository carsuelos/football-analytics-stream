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

/**
 * Shows each new alert as a system notification (on a Mac, in Notification
 * Centre), unless this window is focused, where the alert is already on
 * screen. Each alert notifies at most once while the page is open, so a
 * reconnect or a rewatch doesn't repeat it.
 */
export function useAlertNotifications(on: boolean, alerts: Alert[], status: EngineStatus | null, teams: Team[] | null) {
  const done = useRef(new Set<string>())
  useEffect(() => {
    if (!on || !status || status.state === 'rebuilding' || !supported()) return
    for (const a of alerts) {
      if (done.current.has(a.id) || !fresh(a, status)) continue
      done.current.add(a.id)
      if (document.hasFocus()) continue
      const team = teams?.find((t) => t.id === a.team_id)?.name
      const n = new Notification(`${ALERT_NAMES[a.type]}${team ? ` · ${team}` : ''}`, {
        body: `${matchClock(a)} · ${a.message}`,
        tag: a.id,
      })
      n.onclick = () => {
        window.focus()
        n.close()
      }
    }
  }, [on, alerts, status, teams])
}

function fresh(a: Alert, status: EngineStatus) {
  if (status.period !== a.period || status.match_clock_s === undefined) return false
  const behind = status.match_clock_s - a.match_clock_s
  return behind >= -FRESH_S && behind <= FRESH_S
}
