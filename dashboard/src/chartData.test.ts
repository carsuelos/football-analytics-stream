import { describe, expect, it } from 'vitest'
import { chartPoints, matchTeams } from './chartData'
import { ARGENTINA, FRANCE, matchInfo, snapshot, status } from './test/factories'
import { timeline } from './timeline'

describe('chartPoints', () => {
  const axis = timeline([])

  it('keeps one window, with each team on its side', () => {
    const snapshots = [snapshot(1, 600, 300, [1, 2]), snapshot(1, 600, 600, [3, 4]), snapshot(2, 3600, 300, [5, 6])]
    const points = chartPoints(snapshots, 300, [FRANCE, ARGENTINA], axis)
    expect(points.map((p) => [p.x, p.home.team_id, p.home.pressure_index, p.away.pressure_index])).toEqual([
      [10, FRANCE.id, 2, 1],
      [60, FRANCE.id, 6, 5],
    ])
  })

  it('skips a snapshot without both teams', () => {
    const s = snapshot(1, 600)
    s.teams[1] = { ...s.teams[1], team_id: 1 }
    expect(chartPoints([s], 300, [ARGENTINA, FRANCE], axis)).toEqual([])
  })
})

describe('matchTeams', () => {
  it("takes home and away from the match list, as the engine lists teams as they appear", () => {
    const engine = status({ teams: [FRANCE, ARGENTINA] })
    expect(matchTeams(engine, [matchInfo(1), matchInfo()])).toEqual([ARGENTINA, FRANCE])
  })

  it("falls back to the engine's teams", () => {
    expect(matchTeams(status({ teams: [FRANCE, ARGENTINA] }), null)).toEqual([FRANCE, ARGENTINA])
    expect(matchTeams(status({ teams: [FRANCE, ARGENTINA] }), [matchInfo(1)])).toEqual([FRANCE, ARGENTINA])
  })

  it('is null until both teams are known', () => {
    expect(matchTeams(null, [matchInfo()])).toBeNull()
    expect(matchTeams(status({ teams: [FRANCE] }), null)).toBeNull()
  })
})
