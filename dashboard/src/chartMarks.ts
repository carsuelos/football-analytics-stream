import { ALERT_NAMES } from './alerts'
import { cancelledGoals, describe, isGoal } from './incidents'
import type { Alert } from './schema/alert.schema'
import type { Team } from './schema/engine_status.schema'
import type { Incident } from './schema/incident.schema'
import { matchClock, type Timeline } from './timeline'

export const GOAL = '#f8fafc'
export const RED_CARD = '#ef4444'
export const DISALLOWED = '#a78bfa'

/** What a chart marks: goals (struck through if disallowed), red cards and alerts. */
export interface Mark {
  id: string
  x: number
  colour: string
  shape: 'goal' | 'card' | 'disallowed' | 'alert'
  title: string
}

export function marks(alerts: Alert[], incidents: Incident[], teams: Team[], axis: Timeline): Mark[] {
  const cancelled = cancelledGoals(incidents)
  const teamColour = (id: number) => (id === teams[0].id ? 'var(--color-home)' : 'var(--color-away)')
  const fromIncidents = incidents.flatMap((i): Mark[] => {
    if (i.period === 5) return []
    const title = `${matchClock(i)} · ${describe(i)}`
    if (isGoal(i)) {
      return cancelled.has(i.id)
        ? [{ id: i.id, x: axis.x(i), colour: DISALLOWED, shape: 'disallowed', title: `${title} (disallowed)` }]
        : [{ id: i.id, x: axis.x(i), colour: GOAL, shape: 'goal', title }]
    }
    if (i.kind === 'red_card' || i.kind === 'second_yellow') return [{ id: i.id, x: axis.x(i), colour: RED_CARD, shape: 'card', title }]
    return []
  })
  const fromAlerts = alerts.map(
    (a): Mark => ({ id: a.id, x: axis.x(a), colour: teamColour(a.team_id), shape: 'alert', title: `${matchClock(a)} · ${ALERT_NAMES[a.type]} · ${a.message}` }),
  )
  return [...fromAlerts, ...fromIncidents]
}
