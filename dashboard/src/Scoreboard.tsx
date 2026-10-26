import { useEffect, useState } from 'react'
import { IncidentIcon } from './Icons'
import { INCIDENTS, scoreboardLines, surname, type ScoreboardLine } from './incidents'
import type { Connection } from './matchState'
import type { EngineStatus, Team, TeamScore } from './schema/engine_status.schema'
import type { Incident } from './schema/incident.schema'
import type { MatchInfo } from './schema/match_list.schema'
import { matchClock, matchMinute, periodName } from './timeline'

interface Props {
  /** Home first. */
  teams: Team[]
  status: EngineStatus | null
  incidents: Incident[]
  connection: Connection
  /** The simulator's listing of the match, for its competition. */
  info?: MatchInfo
  /**
   * How fast the match clock runs now (match seconds per second): the
   * broadcast's speed when live, the viewer's when behind, 0 when paused.
   * Between the engine's updates the clock counts on at this rate.
   */
  rate?: number
}

/**
 * A compact scoreboard at the head of the match timeline: the teams, the score
 * (and the shootout's), the clock to the second with stoppage time, and under
 * each team its goals (disallowed ones struck through) and sendings-off.
 */
export function Scoreboard({ teams, status, incidents, connection, info, rate = 0 }: Props) {
  const [home, away] = teams
  const h = goals(home, status, incidents)
  const a = goals(away, status, incidents)
  const shootout = h.shootout !== undefined && a.shootout !== undefined

  return (
    <section
      aria-label="Scoreboard"
      className={`relative overflow-hidden rounded-xl border border-white/[0.06] bg-ink-950/60 px-3 py-3 sm:px-5 ${connection === 'lost' ? 'opacity-50' : ''}`}
    >
      <div className="pointer-events-none absolute inset-y-0 left-0 w-1/3 bg-gradient-to-r from-home/12 to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-1/3 bg-gradient-to-l from-away/12 to-transparent" />
      <div className="relative grid grid-cols-[1fr_auto_1fr] items-center gap-3 sm:gap-6">
        <TeamSide team={home} side="home" lines={scoreboardLines(incidents, home.id)} />
        <div className="flex flex-col items-center">
          <p className="flex items-center gap-2 text-3xl leading-none font-bold tracking-tight tabular-nums sm:text-4xl">
            <span className="sr-only">
              Score: {home.name} {h.goals}, {away.name} {a.goals}
            </span>
            <span aria-hidden="true">{h.goals}</span>
            <span aria-hidden="true" className="text-xl font-light text-slate-500">
              –
            </span>
            <span aria-hidden="true">{a.goals}</span>
          </p>
          {shootout && (
            <p className="mt-1 text-[11px] font-semibold text-slate-300 tabular-nums">
              {h.shootout}–{a.shootout} on penalties
            </p>
          )}
          <Clock status={status} rate={rate} />
        </div>
        <TeamSide team={away} side="away" lines={scoreboardLines(incidents, away.id)} />
      </div>
      <div className="relative mt-2 flex items-center justify-center gap-2 text-[11px] text-slate-500">
        <StatePill status={status} />
        {info && <span className="truncate">{`${info.competition} · ${info.stage}`}</span>}
      </div>
    </section>
  )
}

/** A team's score: from the engine's status, or the latest incident before the first status has one. */
function goals(team: Team, status: EngineStatus | null, incidents: Incident[]): TeamScore {
  const score = status?.score ?? incidents.at(-1)?.score ?? []
  return score.find((s) => s.team_id === team.id) ?? { team_id: team.id, goals: 0 }
}

/**
 * How far the clock may count on past the engine's last update. Its clock is
 * the latest event's, so it stands still between events; counting on keeps it
 * running like a TV's, but a long stop in play holds it until events resume.
 */
const CLOCK_LEAD_S = 20

/**
 * The engine's match clock, counting on between its updates at `rate` (up to
 * CLOCK_LEAD_S ahead) and never going back within a period, except for a seek.
 */
const TICK_MS = 250

function useSmoothClock(period: number | undefined, clock: number | undefined, rate: number): number | undefined {
  const [base, setBase] = useState<Base>({ period, clock })
  const [ahead, setAhead] = useState(0)
  const shown = base.clock === undefined ? undefined : Math.max(base.clock + ahead, base.floor ?? -Infinity)
  if (base.period !== period || base.clock !== clock) {
    // A new update: count on from it, but hold what's shown if it lands behind
    // that (within the lead; further back, or a new period, is a seek).
    const hold = shown !== undefined && clock !== undefined && base.period === period && clock < shown && shown - clock <= CLOCK_LEAD_S
    setBase({ period, clock, floor: hold ? shown : undefined })
    setAhead(0)
  }
  useEffect(() => {
    if (rate <= 0) return
    const timer = setInterval(() => setAhead((a) => Math.min(a + (TICK_MS / 1000) * rate, CLOCK_LEAD_S)), TICK_MS)
    return () => clearInterval(timer)
  }, [rate])
  return shown
}

interface Base {
  period: number | undefined
  clock: number | undefined
  /** Not shown below this: what was shown when an update landed behind it. */
  floor?: number
}

function Clock({ status, rate }: { status: EngineStatus | null; rate: number }) {
  const { period } = status ?? {}
  const match_clock_s = useSmoothClock(period, status?.match_clock_s, rate)
  if (period === undefined || match_clock_s === undefined) {
    return <p className="mt-1 text-xs text-slate-400">Kick-off soon</p>
  }
  if (period === 5) {
    return <p className="mt-1 text-xs font-semibold text-pitch">Penalty shootout</p>
  }
  return (
    <p className="mt-1 flex items-baseline gap-1.5 text-xs">
      <span className="sr-only">Match clock: </span>
      <span className="font-mono text-sm font-semibold text-pitch tabular-nums">{matchClock({ period, match_clock_s })}</span>
      <span className="text-slate-400">{periodName(period)}</span>
    </p>
  )
}

function StatePill({ status }: { status: EngineStatus | null }) {
  const state = status?.state
  if (state === 'live') {
    return (
      <span className="flex items-center gap-1 rounded-full bg-red-500/15 px-2 py-0.5 font-bold tracking-wider text-red-300">
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
  return <span className="rounded-full bg-white/5 px-2 py-0.5 font-semibold tracking-wider text-slate-300 uppercase">{label}</span>
}

function TeamSide({ team, side, lines }: { team: Team; side: 'home' | 'away'; lines: ScoreboardLine[] }) {
  const home = side === 'home'
  return (
    <div className={`flex min-w-0 flex-col gap-1 ${home ? 'items-end text-right' : 'items-start text-left'}`}>
      <div className={`flex max-w-full min-w-0 items-center gap-2 ${home ? 'flex-row-reverse' : ''}`}>
        <span
          className={`grid size-7 shrink-0 place-items-center rounded-full text-[10px] font-bold text-ink-950 ${home ? 'bg-home' : 'bg-away'}`}
          aria-hidden="true"
        >
          {team.name.slice(0, 3).toUpperCase()}
        </span>
        <h2 className="truncate text-sm font-semibold sm:text-lg">{team.name}</h2>
      </div>
      {lines.length > 0 && (
        <ul
          aria-label={`${team.name} goals and red cards`}
          className={`flex flex-wrap gap-x-2.5 gap-y-0.5 text-[11px] text-slate-400 sm:text-xs ${home ? 'justify-end' : ''}`}
        >
          {lines.map(({ incident: i, disallowed }) => (
            <li key={i.id} className={`flex items-center gap-1 ${disallowed ? 'text-slate-600' : ''}`}>
              <IncidentIcon icon={INCIDENTS[i.kind].icon} className="size-3 shrink-0" />
              <span className={disallowed ? 'line-through' : ''}>
                {surname(i.player?.name) ?? INCIDENTS[i.kind].label} {matchMinute(i)}
                {i.kind === 'penalty_goal' ? ' (pen)' : i.kind === 'own_goal' ? ' (og)' : ''}
              </span>
              {disallowed && <span className="rounded bg-violet-500/15 px-1 text-[9px] font-semibold text-violet-300">VAR</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
