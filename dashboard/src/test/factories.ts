import type { Alert } from '../schema/alert.schema'
import type { EngineStatus } from '../schema/engine_status.schema'
import type { MatchReset } from '../schema/match_reset.schema'
import type { MetricSnapshot, TeamMetrics } from '../schema/metric.schema'
import type { MatchInfo } from '../schema/match_list.schema'
import type { PlaybackStatus } from '../schema/status.schema'

export const ARGENTINA = { id: 779, name: 'Argentina' }
export const FRANCE = { id: 771, name: 'France' }

export const reset = (generation = 1, match_id = 3869685): MatchReset => ({ schema_version: 1, generation, match_id })

export const status = (overrides: Partial<EngineStatus> = {}): EngineStatus => ({
  schema_version: 1,
  state: 'live',
  generation: 1,
  match_id: 3869685,
  teams: [ARGENTINA, FRANCE],
  period: 1,
  match_clock_s: 600,
  released: 100,
  buffered: 0,
  late_dropped: 0,
  duplicates: 0,
  ...overrides,
})

const team = (team_id: number, pressure_index: number): TeamMetrics => ({
  team_id,
  field_tilt: 0.5,
  xt_added: 0.1,
  xt_velocity: 0.02,
  pressure_index,
})

export const snapshot = (period: number, match_clock_s: number, window_s = 300, pressure: [number, number] = [5, 5]): MetricSnapshot => ({
  schema_version: 1,
  match_id: 3869685,
  offset: Math.round(match_clock_s),
  period,
  match_clock_s,
  window_s,
  teams: [team(ARGENTINA.id, pressure[0]), team(FRANCE.id, pressure[1])],
})

export const alert = (overrides: Partial<Alert> = {}): Alert => ({
  schema_version: 1,
  id: '3869685-control_shift-771-2808',
  match_id: 3869685,
  offset: 2808,
  period: 2,
  match_clock_s: 4947,
  type: 'control_shift',
  team_id: FRANCE.id,
  value: 0.69,
  threshold: 0.5,
  window_s: 300,
  features: { balance: 0.69, previous: -0.54 },
  message: "France taking control: pressure balance +0.69 over the last 5', from -0.54 the 5' before",
  ...overrides,
})

export const playback = (overrides: Partial<PlaybackStatus> = {}): PlaybackStatus => ({
  schema_version: 1,
  state: 'paused',
  speed: 1,
  match_id: 3869685,
  offset: 0,
  period: 1,
  match_clock_s: 0,
  ...overrides,
})

export const matchInfo = (match_id = 3869685, home = ARGENTINA, away = FRANCE): MatchInfo => ({
  match_id,
  competition: 'FIFA World Cup',
  season: '2022',
  stage: 'Final',
  date: '2022-12-18',
  home_team: home,
  away_team: away,
  home_score: 3,
  away_score: 3,
})

/** A promise and the functions that settle it, for replies that arrive when a test says so. */
export function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}
