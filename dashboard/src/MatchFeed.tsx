import { useMemo, useState } from 'react'
import { AlertIcon, BallIcon, IncidentIcon } from './Icons'
import { ALERT_HORIZON_MIN, cancelledGoals, describe, goalAfter, INCIDENTS, isGoal, scoreline } from './incidents'
import { ALERT_NAMES } from './alerts'
import type { Alert } from './schema/alert.schema'
import type { Team } from './schema/engine_status.schema'
import type { Incident } from './schema/incident.schema'
import { matchClock, type Timeline } from './timeline'
import { segmentClass, segmentsClass } from './ui'

const FILTERS = ['All', 'Events', 'Alerts'] as const
type Filter = (typeof FILTERS)[number]

type Item = { kind: 'incident'; at: number; incident: Incident } | { kind: 'alert'; at: number; alert: Alert }

interface Props {
  /** Home first, or null until the match's teams are known. */
  teams: Team[] | null
  alerts: Alert[]
  incidents: Incident[]
  axis: Timeline
  /** Where the viewer is on the axis, to say when an alert's 10 minutes are up. */
  now?: number
}

/**
 * The match as it happens, latest first: its events (goals, cards,
 * penalties) and the engine's alerts, each alert marked with whether the team
 * went on to score within 10 minutes. A filter shows just one or the other.
 */
export function MatchFeed({ teams, alerts, incidents, axis, now }: Props) {
  const [filter, setFilter] = useState<Filter>('All')
  const items = useMemo(() => {
    const list: Item[] = [
      ...(filter !== 'Alerts' ? incidents.map((incident) => ({ kind: 'incident' as const, at: axis.x(incident), incident })) : []),
      ...(filter !== 'Events' ? alerts.map((alert) => ({ kind: 'alert' as const, at: axis.x(alert), alert })) : []),
    ]
    // Latest first; at the same moment, events before the alerts they explain.
    return list.sort((a, b) => b.at - a.at || (a.kind === b.kind ? 0 : a.kind === 'incident' ? -1 : 1))
  }, [alerts, incidents, axis, filter])
  const cancelled = useMemo(() => cancelledGoals(incidents), [incidents])

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold">Match feed</h2>
        <div role="group" aria-label="Show" className={segmentsClass}>
          {FILTERS.map((f) => (
            <button key={f} type="button" className={segmentClass} aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {f}
            </button>
          ))}
        </div>
      </div>
      {items.length === 0 ? (
        <p className="py-8 text-center text-sm text-slate-400">
          {filter === 'Alerts' ? 'No alerts yet.' : filter === 'Events' ? 'No events yet.' : 'Nothing yet.'}
        </p>
      ) : (
        <ol className="-mr-2 flex max-h-[44rem] flex-col gap-2 overflow-y-auto pr-2">
          {items.map((item) =>
            item.kind === 'incident' ? (
              <IncidentItem key={item.incident.id} incident={item.incident} teams={teams} disallowed={cancelled.has(item.incident.id)} />
            ) : (
              <AlertItem key={item.alert.id} alert={item.alert} teams={teams} incidents={incidents} axis={axis} now={now} />
            ),
          )}
        </ol>
      )}
    </div>
  )
}

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

function AlertItem({ alert: a, teams, incidents, axis, now }: { alert: Alert; teams: Team[] | null; incidents: Incident[]; axis: Timeline; now?: number }) {
  const scored = goalAfter(a, incidents, axis)
  const settled = now !== undefined && now - axis.x(a) > ALERT_HORIZON_MIN
  return (
    <li className={`rounded-xl border-l-[3px] bg-white/[0.03] px-3 py-2.5 ${stripe(a.team_id, teams)}`}>
      <p className="flex items-center gap-2 text-xs text-slate-400">
        <AlertIcon type={a.type} className="size-4 shrink-0 text-sky-300" />
        <span className="font-mono font-semibold tabular-nums text-slate-200">{matchClock(a)}</span>
        <span>· {ALERT_NAMES[a.type]}</span>
        {scored ? (
          <span className="ml-auto flex items-center gap-1 rounded-full bg-emerald-400/15 px-2 py-0.5 font-semibold text-emerald-300">
            <BallIcon className="size-3" /> Scored {minutesLater(scored.minutes)}
          </span>
        ) : (
          settled && <span className="ml-auto rounded-full bg-white/5 px-2 py-0.5 text-slate-500">No goal in 10'</span>
        )}
      </p>
      <p className="mt-1 text-sm text-slate-200">{a.message}</p>
    </li>
  )
}

/** How long after the alert, e.g. "22s later" or "4' later". */
function minutesLater(minutes: number) {
  return minutes < 1 ? `${Math.round(minutes * 60)}s later` : `${Math.floor(minutes)}' later`
}
