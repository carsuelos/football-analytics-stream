import { useMemo, useState } from 'react'
import { AlertIcon, BallIcon, IncidentIcon } from './Icons'
import { ALERT_HORIZON_MIN, cancelledGoals, describe, goalAfter, INCIDENTS, isGoal, scoreline } from './incidents'
import { ALERT_NAMES, isModelAlert } from './alerts'
import type { Alert } from './schema/alert.schema'
import type { Team } from './schema/engine_status.schema'
import type { Incident, IncidentKind } from './schema/incident.schema'
import { matchClock, type Timeline } from './timeline'

/** What the feed can show; each can be switched on and off. */
const CATEGORIES = ['Alerts', 'Goals', 'Cards', 'Penalties'] as const
type Category = (typeof CATEGORIES)[number]

/** The rest are noisier, so start hidden. */
const SHOWN_AT_FIRST: Category[] = ['Alerts', 'Goals']

const KINDS: Record<IncidentKind, Category> = {
  goal: 'Goals',
  own_goal: 'Goals',
  penalty_goal: 'Goals',
  goal_disallowed: 'Goals',
  yellow_card: 'Cards',
  second_yellow: 'Cards',
  red_card: 'Cards',
  penalty_awarded: 'Penalties',
  penalty_missed: 'Penalties',
  shootout_goal: 'Penalties',
  shootout_miss: 'Penalties',
}

type Item = { kind: 'incident'; at: number; incident: Incident } | { kind: 'alert'; at: number; alert: Alert }

interface Props {
  /** Home first, or null until the match's teams are known. */
  teams: Team[] | null
  alerts: Alert[]
  incidents: Incident[]
  axis: Timeline
  /** Where the viewer is on the axis, to say when an alert's 10 minutes are up. */
  now?: number
  /** Whether play is over (full time, or the shootout), so no alert is still waiting on its 10 minutes. */
  over?: boolean
}

/**
 * The match as it happens, latest first: its events (goals, cards,
 * penalties) and the engine's alerts, each alert marked with whether the team
 * went on to score within 10 minutes. A filter shows just one or the other.
 */
export function MatchFeed({ teams, alerts, incidents, axis, now, over = false }: Props) {
  const [shown, setShown] = useState<ReadonlySet<Category>>(() => new Set(SHOWN_AT_FIRST))
  const counts = useMemo(() => {
    const n: Record<Category, number> = { Goals: 0, Cards: 0, Penalties: 0, Alerts: alerts.length }
    for (const i of incidents) n[KINDS[i.kind]] += 1
    return n
  }, [alerts, incidents])
  const items = useMemo(() => {
    const list: Item[] = [
      ...incidents.filter((i) => shown.has(KINDS[i.kind])).map((incident) => ({ kind: 'incident' as const, at: axis.x(incident), incident })),
      ...(shown.has('Alerts') ? alerts.map((alert) => ({ kind: 'alert' as const, at: axis.x(alert), alert })) : []),
    ]
    // Latest first; at the same moment, events before the alerts they explain.
    return list.sort((a, b) => b.at - a.at || (a.kind === b.kind ? 0 : a.kind === 'incident' ? -1 : 1))
  }, [alerts, incidents, axis, shown])
  const cancelled = useMemo(() => cancelledGoals(incidents), [incidents])
  const toggle = (c: Category) =>
    setShown((s) => {
      const next = new Set(s)
      if (!next.delete(c)) next.add(c)
      return next
    })

  return (
    <div className="flex h-full flex-col gap-3">
      <h2 className="font-semibold">Match feed</h2>
      <div role="group" aria-label="Show" className="flex flex-wrap gap-1.5">
        {CATEGORIES.map((c) => (
          <button
            key={c}
            type="button"
            aria-pressed={shown.has(c)}
            onClick={() => toggle(c)}
            className="flex items-center gap-1.5 rounded-full border border-white/10 px-2.5 py-1 text-xs font-medium text-slate-500 transition hover:text-slate-200 aria-pressed:border-sky-400/30 aria-pressed:bg-sky-400/10 aria-pressed:text-sky-100"
          >
            {c}
            <span className="font-mono text-[10px] tabular-nums opacity-70">{counts[c]}</span>
          </button>
        ))}
      </div>
      {items.length === 0 ? (
        <p className="py-8 text-center text-sm text-slate-400">{shown.size === 0 ? 'Choose what to show above.' : 'Nothing yet.'}</p>
      ) : (
        <ol className="-mr-2 flex max-h-[44rem] flex-col gap-2 overflow-y-auto pr-2">
          {items.map((item) =>
            item.kind === 'incident' ? (
              <IncidentItem key={item.incident.id} incident={item.incident} teams={teams} disallowed={cancelled.has(item.incident.id)} />
            ) : (
              <AlertItem key={item.alert.id} alert={item.alert} teams={teams} incidents={incidents} axis={axis} now={now} over={over} />
            ),
          )}
        </ol>
      )}
    </div>
  )
}

/** The model's alerts glow violet, apart from the rules'. */
const MODEL_CARD = 'bg-gradient-to-r from-violet-500/[0.16] via-violet-500/[0.06] to-white/[0.02] ring-1 ring-violet-400/30 shadow-[0_0_28px_-12px_rgba(139,92,246,0.7)]'

function stripe(team_id: number, teams: Team[] | null) {
  if (teams === null) return 'border-slate-600'
  return team_id === teams[0].id ? 'border-home' : 'border-away'
}

function teamName(team_id: number, teams: Team[] | null) {
  return teams?.find((t) => t.id === team_id)?.name
}

function IncidentItem({ incident: i, teams, disallowed }: { incident: Incident; teams: Team[] | null; disallowed: boolean }) {
  const goal = isGoal(i) || i.kind === 'shootout_goal'
  return (
    <li
      className={`animate-flash rounded-xl border-l-[3px] px-3 py-2.5 ${stripe(i.team_id, teams)} ${goal && !disallowed ? 'bg-emerald-400/[0.08] ring-1 ring-emerald-400/20' : 'bg-white/[0.03]'}`}
    >
      <p className="flex items-center gap-2 text-xs text-slate-400">
        <IncidentIcon icon={INCIDENTS[i.kind].icon} className="size-4 shrink-0" />
        <span className="font-mono font-semibold tabular-nums text-slate-200">{matchClock(i)}</span>
        <span>· {teamName(i.team_id, teams)}</span>
        {(isGoal(i) || i.kind === 'goal_disallowed') && (
          <span className="ml-auto font-mono font-semibold tabular-nums text-slate-200">{scoreline(i.score, teams)}</span>
        )}
      </p>
      <p className={`mt-1 text-sm font-medium ${disallowed ? 'text-slate-500 line-through' : ''}`}>{describe(i)}</p>
      {disallowed && <p className="mt-0.5 text-xs text-violet-300">Disallowed after review</p>}
    </li>
  )
}

function AlertItem({
  alert: a,
  teams,
  incidents,
  axis,
  now,
  over,
}: {
  alert: Alert
  teams: Team[] | null
  incidents: Incident[]
  axis: Timeline
  now?: number
  over: boolean
}) {
  // Worked out here, from the goals the viewer has seen so far: the alert itself never changes.
  const scored = goalAfter(a, incidents, axis)
  const model = isModelAlert(a.type)
  const elapsed = now === undefined ? undefined : now - axis.x(a)
  return (
    <li className={`rounded-xl border-l-[3px] px-3 py-2.5 ${stripe(a.team_id, teams)} ${model ? MODEL_CARD : 'bg-white/[0.03]'}`}>
      <p className="flex items-center gap-2 text-xs text-slate-400">
        <AlertIcon type={a.type} className={`size-4 shrink-0 ${model ? 'text-violet-300' : 'text-sky-300'}`} />
        <span className="font-mono font-semibold text-slate-200 tabular-nums">{matchClock(a)}</span>
        <span className={model ? 'font-semibold text-violet-200' : undefined}>· {ALERT_NAMES[a.type]}</span>
        {scored?.counts ? (
          <span title={OUTCOME_HINT} className="ml-auto flex items-center gap-1 rounded-full bg-emerald-400/15 px-2 py-0.5 font-semibold text-emerald-300">
            <BallIcon className="size-3" /> Scored {minutesLater(scored.minutes)}
          </span>
        ) : scored ? (
          <span title={TOO_SOON_HINT} className="ml-auto flex items-center gap-1 rounded-full bg-white/5 px-2 py-0.5 text-slate-400">
            <BallIcon className="size-3 opacity-60" /> Goal {minutesLater(scored.minutes)}, too soon to count
          </span>
        ) : (elapsed !== undefined && elapsed > ALERT_HORIZON_MIN) || over ? (
          <span title={OUTCOME_HINT} className="ml-auto rounded-full bg-rose-400/10 px-2 py-0.5 text-rose-300/80">
            {elapsed !== undefined && elapsed <= ALERT_HORIZON_MIN ? 'No goal by full time' : "No goal in 10'"}
          </span>
        ) : elapsed === undefined ? null : (
          <span title={OUTCOME_HINT} className="ml-auto rounded-full border border-sky-400/20 px-2 py-0.5 text-sky-300/80">
            Watching · {Math.min(ALERT_HORIZON_MIN, Math.max(1, Math.ceil(ALERT_HORIZON_MIN - elapsed)))}' left
          </span>
        )}
      </p>
      <p className="mt-1 text-sm text-slate-200">{a.message.split(FULL_TIME_SUFFIX)[0]}</p>
      <FullTimeLines alert={a} team={teams?.find((t) => t.id === a.team_id)?.name} />
    </li>
  )
}

/** Where the engine's message says what the next lines are worth; shown as chips instead. */
const FULL_TIME_SUFFIX = '. By full time:'

/**
 * What the full-time model says the prediction markets' next "over" lines are
 * worth at the alert: the team's (it scores again) and the match's (anyone does).
 */
function FullTimeLines({ alert: a, team }: { alert: Alert; team?: string }) {
  const { ft_team, team_line, ft_game, game_line } = a.features
  if (ft_team === undefined || ft_game === undefined) return null
  const chip = 'rounded-full border border-white/10 bg-white/[0.03] px-2 py-0.5 text-slate-300 tabular-nums'
  return (
    <p aria-label="By full time" className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px]">
      <span className="text-slate-500">By full time</span>
      <span className={chip} title={`Our chance that ${team ?? 'this team'} scores again before full time: what "over ${team_line}" pays on`}>
        {team ?? 'Team'} over {team_line} · <span className="font-semibold text-slate-100">{percent(ft_team)}</span>
      </span>
      <span className={chip} title={`Our chance of another goal by anyone before full time: what "over ${game_line}" pays on`}>
        Over {game_line} · <span className="font-semibold text-slate-100">{percent(ft_game)}</span>
      </span>
    </p>
  )
}

const percent = (p: number) => `${Math.round(p * 100)}%`

const OUTCOME_HINT =
  'Checked as the match plays on: did this team score from 30 seconds to 10 minutes after the alert?'

const TOO_SOON_HINT =
  'The goal came less than 30 seconds after the alert: the attack was already under way, so it does not count as predicted.'

/** How long after the alert, e.g. "22s later" or "4' later". */
function minutesLater(minutes: number) {
  return minutes < 1 ? `${Math.max(1, Math.round(minutes * 60))}s later` : `${Math.floor(minutes)}' later`
}
