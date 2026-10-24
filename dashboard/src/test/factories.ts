import type { Alert } from '../schema/alert.schema'
import type { EngineStatus } from '../schema/engine_status.schema'
import type { Incident } from '../schema/incident.schema'
import type { MarketBoard } from '../schema/market_board.schema'
import type { MatchReset } from '../schema/match_reset.schema'
import type { MetricSnapshot, TeamMetrics } from '../schema/metric.schema'
import type { MatchInfo } from '../schema/match_list.schema'
import type { BroadcastStatus } from '../schema/broadcast_status.schema'

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

/** Di María's goal in the 2022 final, Argentina 2-0 up. */
export const incident = (overrides: Partial<Incident> = {}): Incident => ({
  schema_version: 1,
  id: '3869685-di-maria-goal',
  match_id: 3869685,
  offset: 1013,
  period: 1,
  match_clock_s: 2122.5,
  play_s: 2122.5,
  kind: 'goal',
  team_id: ARGENTINA.id,
  player: { id: 5487, name: 'Ángel Di María' },
  score: [
    { team_id: ARGENTINA.id, goals: 2 },
    { team_id: FRANCE.id, goals: 0 },
  ],
  ...overrides,
})

export const broadcast = (overrides: Partial<BroadcastStatus> = {}): BroadcastStatus => ({
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

/** A market board: Chelsea v Tottenham live at 1-0 on all three venues, and a game tomorrow on Kalshi only. */
export const marketBoard = (overrides: Partial<MarketBoard> = {}): MarketBoard => ({
  schema_version: 1,
  league: 'epl',
  updated_at: '2026-10-24T17:50:40Z',
  venues: [
    { venue: 'kalshi', ok: true, updated_at: '2026-10-24T17:50:38Z', games: 2 },
    { venue: 'polymarket', ok: true, updated_at: '2026-10-24T17:50:38Z', games: 1 },
    { venue: 'novig', ok: false, error: '429 Too Many Requests', updated_at: '2026-10-24T17:48:00Z', games: 1 },
  ],
  games: [
    {
      id: 'epl-2026-10-24-chelsea-tottenham',
      league: 'epl',
      home: { name: 'Chelsea', abbreviation: 'CFC', color: '#034694' },
      away: { name: 'Tottenham', abbreviation: 'TOT', color: '#001C58' },
      kickoff: '2026-10-24T16:30:00Z',
      state: 'live',
      score: { home: 1, away: 0 },
      clock: "63'",
      listings: [
        { venue: 'polymarket', event_id: '164610', url: 'https://polymarket.us/event/epl-cfc-tot-2026-10-24' },
        { venue: 'novig', event_id: 'nv-1' },
        { venue: 'kalshi', event_id: '26OCT24CFCTOT' },
      ],
      contracts: [
        {
          key: 'total-over-0.5',
          kind: 'total',
          outcome: 'over',
          line: 0.5,
          label: 'Over 0.5',
          quotes: [{ venue: 'kalshi', market_id: 'K-1', bid: 0.99 }],
        },
        {
          key: 'total-over-1.5',
          kind: 'total',
          outcome: 'over',
          line: 1.5,
          label: 'Over 1.5',
          quotes: [
            { venue: 'kalshi', market_id: 'K-2', bid: 0.47, ask: 0.48, fee: 0.01747, all_in: 0.49747 },
            { venue: 'novig', market_id: 'N-2', bid: 0.47, ask: 0.49, fee: 0.0, all_in: 0.49 },
          ],
          best: 'novig',
          implied: 0.49,
        },
        {
          key: 'result-draw',
          kind: 'result',
          outcome: 'draw',
          label: 'Draw',
          quotes: [{ venue: 'polymarket', market_id: 'P-draw', bid: 0.22, ask: 0.23, fee: 0.0123, all_in: 0.2423 }],
          best: 'polymarket',
          implied: 0.2423,
        },
        {
          key: 'team-home-over-0.5',
          kind: 'team_total',
          outcome: 'home',
          line: 0.5,
          label: 'Chelsea over 0.5',
          quotes: [{ venue: 'kalshi', market_id: 'K-CFC1', bid: 0.99 }],
        },
        {
          key: 'team-away-over-0.5',
          kind: 'team_total',
          outcome: 'away',
          line: 0.5,
          label: 'Tottenham over 0.5',
          quotes: [
            { venue: 'kalshi', market_id: 'K-TOT1', bid: 0.3, ask: 0.32, ask_size: 50, fee: 0.0152, all_in: 0.3352 },
            { venue: 'polymarket', market_id: 'P-TOT1', bid: 0.31, ask: 0.33, fee: 0.0154, all_in: 0.3454 },
          ],
          best: 'kalshi',
          implied: 0.3352,
        },
      ],
    },
    {
      id: 'epl-2026-10-25-crystal-palace-newcastle',
      league: 'epl',
      home: { name: 'Crystal Palace' },
      away: { name: 'Newcastle' },
      kickoff: '2026-10-25T14:00:00Z',
      kickoff_estimated: true,
      state: 'scheduled',
      listings: [{ venue: 'kalshi', event_id: '26OCT25CRYNEW' }],
      contracts: [],
    },
  ],
  ...overrides,
})
