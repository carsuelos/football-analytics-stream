import { IncidentIcon } from './Icons'
import { INCIDENTS, scoreboardLines, type ScoreboardLine } from './incidents'
import type { Connection } from './matchState'
import type { EngineStatus, Team, TeamScore } from './schema/engine_status.schema'
import type { Incident } from './schema/incident.schema'
import type { MatchInfo } from './schema/match_list.schema'
import { matchClock, matchMinute, periodName } from './timeline'

interface Props {
  /** Home first, or null until the match's teams are known. */
  teams: Team[] | null
  status: EngineStatus | null
  incidents: Incident[]
  connection: Connection
  /** The simulator's listing of the match, for its competition. */
  info?: MatchInfo
}

/**
 * The match as a broadcast shows it: the teams, the score (and the shootout's),
 * the clock to the second with stoppage time, and under each team its goals
 * (disallowed ones struck through) and sendings-off.
 */
export function Scoreboard({ teams, status, incidents, connection, info }: Props) {
  if (teams === null) {
    return (
      <section aria-label="Scoreboard" className="card flex h-36 items-center justify-center text-slate-400">
        No match on yet
      </section>
    )
  }
  const [home, away] = teams
  const score = (team: Team) => goals(team, status, incidents)
  const h = score(home)
  const a = score(away)
  const shootout = h.shootout !== undefined && a.shootout !== undefined
  const dim = connection === 'lost' ? 'opacity-50' : ''

  return (
    <section aria-label="Scoreboard" className={`card relative overflow-hidden px-4 py-5 sm:px-8 ${dim}`}>
      <div className="pointer-events-none absolute inset-y-0 left-0 w-1/2 bg-gradient-to-r from-home/15 to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-1/2 bg-gradient-to-l from-away/15 to-transparent" />
      <div className="relative flex items-center justify-between gap-2">
        <p className="eyebrow truncate">{info ? `${info.competition} · ${info.stage}` : 'Live match'}</p>
        <StatePill status={status} />
      </div>
      <div className="relative mt-4 grid grid-cols-[1fr_auto_1fr] items-start gap-3 sm:gap-8">
        <TeamSide team={home} side="home" lines={scoreboardLines(incidents, home.id)} />
        <div className="flex flex-col items-center gap-1.5">
          <p className="flex items-center gap-2 text-4xl font-bold tabular-nums tracking-tight sm:gap-3 sm:text-6xl">
            <span className="sr-only">
              Score: {home.name} {h.goals}, {away.name} {a.goals}
            </span>
            <span aria-hidden="true">{h.goals}</span>
            <span aria-hidden="true" className="text-3xl font-light text-slate-500">
              –
            </span>
            <span aria-hidden="true">{a.goals}</span>
          </p>
          {shootout && (
            <p className="rounded-full bg-white/5 px-2.5 py-0.5 text-xs font-semibold tabular-nums text-slate-300">
              {h.shootout}–{a.shootout} on penalties
            </p>
          )}
          <Clock status={status} />
        </div>
        <TeamSide team={away} side="away" lines={scoreboardLines(incidents, away.id)} />
      </div>
    </section>
  )
}

/** A team's score: from the engine's status, or the latest incident before the first status has one. */
function goals(team: Team, status: EngineStatus | null, incidents: Incident[]): TeamScore {
  const score = status?.score ?? incidents.at(-1)?.score ?? []
  return score.find((s) => s.team_id === team.id) ?? { team_id: team.id, goals: 0 }
}

function Clock({ status }: { status: EngineStatus | null }) {
  const { period, match_clock_s } = status ?? {}
  if (period === undefined || match_clock_s === undefined) {
    return <p className="text-sm text-slate-400">Kick-off soon</p>
  }
  if (period === 5) {
    return <p className="text-sm font-semibold text-pitch">Penalty shootout</p>
  }
  return (
    <p className="flex flex-col items-center leading-tight">
      <span className="sr-only">Match clock: </span>
      <span className="font-mono text-lg font-semibold tabular-nums text-pitch">{matchClock({ period, match_clock_s })}</span>
      <span className="text-xs text-slate-400">{periodName(period)}</span>
    </p>
  )
}

function StatePill({ status }: { status: EngineStatus | null }) {
  const state = status?.state
  if (state === 'live') {
    return (
      <span className="flex items-center gap-1.5 rounded-full bg-red-500/15 px-2.5 py-1 text-[11px] font-bold tracking-wider text-red-300">
        <span className="size-1.5 animate-live rounded-full bg-red-500" /> LIVE
      </span>
    )
  }
  const label =
    state === 'playing'
      ? `Replay · ${status?.speed ?? 1}×`
      : state === 'paused'
        ? 'Paused'
        : state === 'ended'
          ? 'Full time'
          : state === 'rebuilding'
            ? 'Catching up'
            : 'Waiting'
  return <span className="rounded-full bg-white/5 px-2.5 py-1 text-[11px] font-semibold tracking-wider text-slate-300 uppercase">{label}</span>
}

function TeamSide({ team, side, lines }: { team: Team; side: 'home' | 'away'; lines: ScoreboardLine[] }) {
  const right = side === 'home'
  return (
    <div className={`flex min-w-0 flex-col gap-2 ${right ? 'items-end text-right' : 'items-start text-left'}`}>
      <div className={`flex max-w-full min-w-0 flex-col gap-1.5 sm:items-center sm:gap-3 ${right ? 'items-end sm:flex-row-reverse' : 'items-start sm:flex-row'}`}>
        <span
          className={`grid size-9 shrink-0 sm:size-11 place-items-center rounded-full text-xs font-bold tracking-wide text-ink-950 shadow-lg ${right ? 'bg-home shadow-home/30' : 'bg-away shadow-away/30'}`}
          aria-hidden="true"
        >
          {team.name.slice(0, 3).toUpperCase()}
        </span>
        <h2 className="max-w-full truncate text-base font-semibold sm:text-2xl">{team.name}</h2>
      </div>
      {lines.length > 0 && (
        <ul aria-label={`${team.name} goals and red cards`} className="flex flex-col gap-0.5 text-xs text-slate-300 sm:text-sm">
          {lines.map(({ incident: i, disallowed }) => (
            <li key={i.id} className={`flex items-center gap-1.5 ${right ? 'flex-row-reverse' : ''} ${disallowed ? 'text-slate-500' : ''}`}>
              <IncidentIcon icon={INCIDENTS[i.kind].icon} className="size-3.5 shrink-0" />
              <span className={disallowed ? 'line-through' : ''}>
                {i.player?.name ?? INCIDENTS[i.kind].label} {matchMinute(i)}
                {i.kind === 'penalty_goal' ? ' (pen)' : i.kind === 'own_goal' ? ' (og)' : ''}
              </span>
              {disallowed && <span className="rounded bg-violet-500/15 px-1 text-[10px] font-semibold text-violet-300">VAR</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
