import type { EngineStatus, Team } from './schema/engine_status.schema'
import type { MatchInfo } from './schema/match_list.schema'
import type { MetricSnapshot, TeamMetrics } from './schema/metric.schema'
import type { Timeline } from './timeline'

/** One snapshot as a chart point: its axis position and each team's metrics, home first. */
export interface ChartPoint {
  x: number
  home: TeamMetrics
  away: TeamMetrics
}

/** The snapshots for one window length, as points on the timeline. */
export function chartPoints(
  snapshots: MetricSnapshot[],
  window_s: number,
  [home, away]: Team[],
  axis: Timeline,
): ChartPoint[] {
  const points: ChartPoint[] = []
  for (const s of snapshots) {
    if (s.window_s !== window_s) continue
    const h = s.teams.find((t) => t.team_id === home.id)
    const a = s.teams.find((t) => t.team_id === away.id)
    if (h && a) {
      points.push({ x: axis.x(s), home: h, away: a })
    }
  }
  return points
}

/**
 * The match's teams, home first. The engine lists them in order of first
 * appearance, so prefer the simulator's match list, which knows home from away.
 */
export function matchTeams(status: EngineStatus | null, matches: MatchInfo[] | null): Team[] | null {
  const info = matches?.find((m) => m.match_id === status?.match_id)
  if (info) return [info.home_team, info.away_team]
  return status?.teams?.length === 2 ? status.teams : null
}
