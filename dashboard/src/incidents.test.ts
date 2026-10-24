import { describe as group, expect, it } from 'vitest'
import { cancelledGoals, describe, goalAfter, scoreboardLines, scoreline, surname } from './incidents'
import { alert, ARGENTINA, FRANCE, incident } from './test/factories'
import { timeline } from './timeline'

const TEAMS = [ARGENTINA, FRANCE]

group('incidents', () => {
  it('describes an incident in a line', () => {
    expect(describe(incident())).toBe('Goal · Ángel Di María')
    expect(describe(incident({ kind: 'penalty_goal', player: { id: 1, name: 'Lionel Messi' } }))).toBe(
      'Penalty scored · Lionel Messi',
    )
    expect(describe(incident({ kind: 'goal_disallowed', reason: 'offside' }))).toBe(
      'Goal disallowed (offside) · Ángel Di María',
    )
    expect(describe(incident({ kind: 'yellow_card', player: undefined }))).toBe('Yellow card')
    expect(describe(incident({ kind: 'penalty_awarded', player: { id: 2, name: 'Ousmane Dembélé' } }))).toBe(
      'Penalty awarded · conceded by Ousmane Dembélé',
    )
  })

  it('writes the score home first, with the shootout once it has started', () => {
    const score = [
      { team_id: FRANCE.id, goals: 3, shootout: 2 },
      { team_id: ARGENTINA.id, goals: 3, shootout: 4 },
    ]
    expect(scoreline(score, TEAMS)).toBe('3–3 (4–2 pens)')
    expect(scoreline(incident().score, TEAMS)).toBe('2–0')
    expect(scoreline(incident().score, null)).toBe('2–0')
  })

  it('marks goals that were disallowed, and lists sendings-off', () => {
    const goal = incident({ id: 'g' })
    const incidents = [
      goal,
      incident({ id: 'v', kind: 'goal_disallowed', cancels: 'g', reason: 'offside' }),
      incident({ id: 'g2', kind: 'penalty_goal', match_clock_s: 3000 }),
      incident({ id: 'y', kind: 'yellow_card' }),
      incident({ id: 'r', kind: 'red_card' }),
      incident({ id: 'f', team_id: FRANCE.id }),
    ]
    expect(cancelledGoals(incidents)).toEqual(new Set(['g']))
    expect(scoreboardLines(incidents, ARGENTINA.id).map((l) => [l.incident.id, l.disallowed])).toEqual([
      ['g', true],
      ['g2', false],
      ['r', false],
    ])
  })

  it("finds the alerted team's goal from 30 seconds to 10 minutes after an alert", () => {
    const axis = timeline([])
    const a = alert({ team_id: ARGENTINA.id, period: 1, match_clock_s: 35 * 60 })
    const goal = incident({ match_clock_s: 35 * 60 + 37 })
    expect(goalAfter(a, [goal], axis)).toMatchObject({ counts: true })
    expect(goalAfter(a, [goal], axis)?.minutes).toBeCloseTo(37 / 60)
    expect(goalAfter(a, [incident({ match_clock_s: 35 * 60 + 30 })], axis)?.counts).toBe(true) // just in time
    expect(goalAfter(a, [incident({ match_clock_s: 46 * 60 })], axis)).toBeNull() // too late
    expect(goalAfter(a, [incident({ match_clock_s: 34 * 60 })], axis)).toBeNull() // before
    expect(goalAfter(a, [incident({ team_id: FRANCE.id })], axis)).toBeNull() // the other team
    const var_ = incident({ id: 'v', kind: 'goal_disallowed', cancels: goal.id })
    expect(goalAfter(a, [goal, var_], axis)).toBeNull()
  })

  it('reports a goal too soon after the alert, unless a later one counts', () => {
    const axis = timeline([])
    const a = alert({ team_id: ARGENTINA.id, period: 1, match_clock_s: 35 * 60 })
    const soon = incident({ id: 's', match_clock_s: 35 * 60 + 3 })
    const later = incident({ id: 'l', match_clock_s: 40 * 60 })
    expect(goalAfter(a, [soon], axis)).toMatchObject({ incident: soon, counts: false })
    expect(goalAfter(a, [soon, later], axis)).toMatchObject({ incident: later, counts: true })
  })

  it('shortens a name to what a scoreboard shows', () => {
    expect(surname('Ángel Di María')).toBe('Di María')
    expect(surname('Kylian Mbappé')).toBe('Mbappé')
    expect(surname('Pedri')).toBe('Pedri')
    expect(surname(undefined)).toBeUndefined()
  })
})
