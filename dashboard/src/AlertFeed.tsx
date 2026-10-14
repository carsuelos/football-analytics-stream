import { useMemo } from 'react'
import type { Alert, AlertType } from './schema/alert.schema'
import type { Team } from './schema/engine_status.schema'
import { matchMinute } from './timeline'

const TYPE_NAMES: Record<AlertType, string> = {
  momentum_shift: 'Momentum',
  goal_threat: 'Goal threat',
  control_shift: 'Control shift',
  goal_chance: 'Goal chance (model)',
}

function teamBorder(team_id: number, teams: Team[] | null) {
  if (teams === null) return 'border-slate-600'
  return team_id === teams[0].id ? 'border-home' : 'border-away'
}

interface Props {
  /** Home first, or null until the match's teams are known. */
  teams: Team[] | null
  alerts: Alert[]
}

/** The match's alerts, latest in the match first, coloured by team. */
export function AlertFeed({ teams, alerts }: Props) {
  // Alerts arrive roughly in match order, but not exactly, so sort them.
  const latestFirst = useMemo(
    () => [...alerts].sort((a, b) => b.period - a.period || b.match_clock_s - a.match_clock_s),
    [alerts],
  )

  return (
    <div className="flex flex-col gap-3">
      <h2 className="font-semibold">Alerts</h2>
      {latestFirst.length === 0 ? (
        <p className="text-sm text-slate-400">No alerts yet.</p>
      ) : (
        <ol className="flex max-h-[36rem] flex-col gap-2 overflow-y-auto">
          {latestFirst.map((a) => (
            <li
              key={a.id}
              className={`rounded-md border-l-4 bg-slate-800 px-3 py-2 ${teamBorder(a.team_id, teams)}`}
            >
              <p className="text-xs text-slate-400">
                <span className="font-semibold text-slate-200">{matchMinute(a)}</span> · {TYPE_NAMES[a.type]}
              </p>
              <p className="text-sm">{a.message}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
