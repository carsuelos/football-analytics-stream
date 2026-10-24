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
 * How long before a goal an alert must come to count as predicting it, in
 * minutes: a second before is the attack that scored, already under way. The
 * engine's evaluation and training use the same (engine.backtest.MIN_LEAD_S).
 */
export const ALERT_MIN_LEAD_MIN = 0.5

export interface GoalAfter {
  incident: Incident
  /** Minutes of play from the alert to the goal. */
  minutes: number
  /** Whether it came late enough after the alert to count as predicted. */
  counts: boolean
}

/**
 * The alerted team's goal within ALERT_HORIZON_MIN minutes of play after the
 * alert (disallowed goals don't count): the first that came at least
 * ALERT_MIN_LEAD_MIN later, or else the first, too soon to count.
 */
export function goalAfter(alert: Alert, incidents: Incident[], axis: Timeline): GoalAfter | null {
  const cancelled = cancelledGoals(incidents)
  const from = axis.x(alert)
  let tooSoon: GoalAfter | null = null
  for (const i of incidents) {
    if (!isGoal(i) || i.team_id !== alert.team_id || cancelled.has(i.id) || i.period === 5) continue
    const minutes = axis.x(i) - from
    if (minutes <= 0 || minutes > ALERT_HORIZON_MIN) continue
    if (minutes >= ALERT_MIN_LEAD_MIN - 1e-9) return { incident: i, minutes, counts: true }
    tooSoon ??= { incident: i, minutes, counts: false }
  }
  return tooSoon
}

/** The name without the first name, as on a scoreboard: "Di María", "Mbappé". */
export function surname(name: string | undefined) {
  if (!name) return undefined
  const parts = name.split(' ')
  return parts.length > 1 ? parts.slice(1).join(' ') : name
}
