import type { Alert } from './schema/alert.schema'
import type { Team, TeamScore } from './schema/engine_status.schema'
import type { Incident, IncidentKind } from './schema/incident.schema'
import type { Timeline } from './timeline'

export type IncidentIcon = 'goal' | 'own_goal' | 'yellow' | 'red' | 'second_yellow' | 'penalty' | 'missed' | 'var'

export const INCIDENTS: Record<IncidentKind, { label: string; icon: IncidentIcon }> = {
  goal: { label: 'Goal', icon: 'goal' },
  own_goal: { label: 'Own goal', icon: 'own_goal' },
  penalty_goal: { label: 'Penalty scored', icon: 'goal' },
  penalty_missed: { label: 'Penalty missed', icon: 'missed' },
  penalty_awarded: { label: 'Penalty awarded', icon: 'penalty' },
  goal_disallowed: { label: 'Goal disallowed', icon: 'var' },
  yellow_card: { label: 'Yellow card', icon: 'yellow' },
  second_yellow: { label: 'Second yellow, sent off', icon: 'second_yellow' },
  red_card: { label: 'Red card', icon: 'red' },
  shootout_goal: { label: 'Shootout: scored', icon: 'goal' },
  shootout_miss: { label: 'Shootout: missed', icon: 'missed' },
}

const REASONS = { offside: 'offside', foul: 'foul', handball: 'handball', other: 'VAR review' }

export const isGoal = (i: Incident) => i.kind === 'goal' || i.kind === 'own_goal' || i.kind === 'penalty_goal'

/** The ids of goals a later goal_disallowed cancelled. */
export function cancelledGoals(incidents: Incident[]): Set<string> {
  return new Set(incidents.flatMap((i) => (i.kind === 'goal_disallowed' && i.cancels ? [i.cancels] : [])))
}

/**
 * One line about an incident, e.g. "Penalty scored · Lionel Messi",
 * "Penalty awarded · conceded by Ousmane Dembélé" or "Goal disallowed (offside) · Lautaro Martínez".
 */
export function describe(i: Incident): string {
  const label = i.kind === 'goal_disallowed' && i.reason ? `Goal disallowed (${REASONS[i.reason]})` : INCIDENTS[i.kind].label
  if (!i.player) return label
  // The player on a penalty award is the one who gave it away.
  return i.kind === 'penalty_awarded' ? `${label} · conceded by ${i.player.name}` : `${label} · ${i.player.name}`
}

/** The score after an incident, home first, e.g. "2–0", with the shootout's once it has started. */
export function scoreline(score: TeamScore[], teams: Team[] | null): string {
  const ordered = teams ? teams.map((t) => score.find((s) => s.team_id === t.id)) : score
  const [h, a] = ordered
  if (!h || !a) return ''
  const pens = h.shootout !== undefined && a.shootout !== undefined ? ` (${h.shootout}–${a.shootout} pens)` : ''
  return `${h.goals}–${a.goals}${pens}`
}

/** The incidents that belong on a scoreboard: goals (cancelled ones marked) and sendings-off. */
export interface ScoreboardLine {
  incident: Incident
  disallowed: boolean
}

export function scoreboardLines(incidents: Incident[], teamId: number): ScoreboardLine[] {
  const cancelled = cancelledGoals(incidents)
  return incidents
    .filter((i) => i.team_id === teamId && (isGoal(i) || i.kind === 'red_card' || i.kind === 'second_yellow'))
    .map((incident) => ({ incident, disallowed: cancelled.has(incident.id) }))
}

/** The horizon the alerts are judged over, in minutes of play. */
export const ALERT_HORIZON_MIN = 10

/**
 * The first goal the alerted team scored within ALERT_HORIZON_MIN minutes of
 * play after the alert, if any (disallowed goals don't count).
 */
export function goalAfter(alert: Alert, incidents: Incident[], axis: Timeline): { incident: Incident; minutes: number } | null {
  const cancelled = cancelledGoals(incidents)
  const from = axis.x(alert)
  for (const i of incidents) {
    if (!isGoal(i) || i.team_id !== alert.team_id || cancelled.has(i.id) || i.period === 5) continue
    const minutes = axis.x(i) - from
    if (minutes > 0 && minutes <= ALERT_HORIZON_MIN) return { incident: i, minutes }
  }
  return null
}
