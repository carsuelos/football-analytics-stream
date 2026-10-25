import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { MatchFeed } from './MatchFeed'
import { alert, ARGENTINA, FRANCE, incident } from './test/factories'
import { timeline } from './timeline'

const TEAMS = [ARGENTINA, FRANCE]
const axis = timeline([])

const control = alert({ id: 'a', team_id: ARGENTINA.id, period: 1, match_clock_s: 34 * 60 + 45, message: 'Argentina in control' })
const threat = alert({ id: 'b', type: 'goal_threat', team_id: FRANCE.id, period: 1, match_clock_s: 20 * 60, message: 'France goal threat 20%' })
const goal = incident()

describe('MatchFeed', () => {
  it('says when there is nothing yet', () => {
    render(<MatchFeed teams={TEAMS} alerts={[]} incidents={[]} axis={axis} />)
    expect(screen.getByText('Nothing yet.')).toBeInTheDocument()
  })

  it('lists events and alerts latest first, to the second, and marks the alerts that came true', () => {
    const pressing = alert({ id: 'c', type: 'momentum_shift', team_id: FRANCE.id, period: 1, match_clock_s: 36 * 60, message: 'France momentum' })
    render(<MatchFeed teams={TEAMS} alerts={[control, threat, pressing]} incidents={[goal]} axis={axis} now={40} />)
    const items = screen.getAllByRole('listitem')
    expect(items.map((li) => li.textContent)).toEqual([
      "36:00· MomentumWatching · 6' leftFrance momentum",
      '35:22· Argentina2–0Goal · Ángel Di María',
      '34:45· Control Scored 38s laterArgentina in control',
      "20:00· Goal threatNo goal in 10'France goal threat 20%",
    ])
    expect(items.map((li) => li.className.match(/border-(home|away)/)?.[1])).toEqual(['away', 'home', 'home', 'away'])
  })

  it('shows alerts and goals at first, and can show cards and penalties too, with how many of each', async () => {
    const card = incident({ id: 'y', kind: 'yellow_card', match_clock_s: 40 * 60 })
    const award = incident({ id: 'p', kind: 'penalty_awarded', match_clock_s: 20 * 60 })
    const kicks = incident({ id: 's', kind: 'shootout_miss', period: 5, match_clock_s: 7300 })
    render(<MatchFeed teams={TEAMS} alerts={[control]} incidents={[goal, card, award, kicks]} axis={axis} />)
    const filters = screen.getByRole('group', { name: 'Show' })
    expect(filters).toHaveTextContent('Alerts1Goals1Cards1Penalties2')
    expect(screen.getByRole('button', { name: /^Cards/ })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      '35:22· Argentina2–0Goal · Ángel Di María',
      '34:45· Control Scored 38s laterArgentina in control',
    ])

    await userEvent.click(screen.getByRole('button', { name: /^Cards/ }))
    await userEvent.click(screen.getByRole('button', { name: /^Penalties/ }))
    expect(screen.getAllByRole('listitem')).toHaveLength(5)

    for (const name of [/^Alerts/, /^Goals/, /^Cards/, /^Penalties/]) {
      await userEvent.click(screen.getByRole('button', { name }))
    }
    expect(screen.getByText('Choose what to show above.')).toBeInTheDocument()
  })

  it('settles every alert once play is over, as in the shootout', () => {
    const late = alert({ id: 'l', team_id: FRANCE.id, period: 4, match_clock_s: 117 * 60, message: 'France late on' })
    const played = timeline([threat, late, { period: 4, match_clock_s: 121 * 60 }])
    render(<MatchFeed teams={TEAMS} alerts={[threat, late]} incidents={[]} axis={played} now={played.domain[1]} over />)
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      "117:00· ControlNo goal by full timeFrance late on",
      "20:00· Goal threatNo goal in 10'France goal threat 20%",
    ])
  })

  it('says when the goal came too soon after the alert to count', () => {
    const late = alert({ id: 'z', team_id: ARGENTINA.id, period: 1, match_clock_s: 35 * 60 + 20, message: 'Argentina goal threat' })
    render(<MatchFeed teams={TEAMS} alerts={[late]} incidents={[goal]} axis={axis} now={40} />)
    expect(screen.getByText(/Goal \ds later, too soon to count/)).toBeInTheDocument()
    expect(screen.queryByText(/Scored/)).toBeNull()
  })

  it('shows a disallowed goal struck through, and an alert before it unscored', () => {
    const var_ = incident({ id: 'v', kind: 'goal_disallowed', cancels: goal.id, reason: 'offside', match_clock_s: 36 * 60 })
    render(<MatchFeed teams={TEAMS} alerts={[control]} incidents={[goal, var_]} axis={axis} />)
    expect(screen.getByText('Disallowed after review')).toBeInTheDocument()
    expect(screen.getByText('Goal disallowed (offside) · Ángel Di María')).toBeInTheDocument()
    expect(screen.queryByText(/Scored/)).toBeNull()
  })

  it("shows what the next lines are worth by full time, from the model's alerts", () => {
    const chance = alert({
      type: 'goal_chance',
      team_id: ARGENTINA.id,
      period: 1,
      match_clock_s: 36 * 60 + 53,
      features: { base_rate: 0.13, ft_team: 0.634, team_line: 2.5, ft_game: 0.81, game_line: 2.5 },
      message: "Argentina: 19% chance to score in the next 10' (usually 13%). By full time: 63% to score again (Argentina over 2.5), 81% for any goal (over 2.5)",
    })
    render(<MatchFeed teams={TEAMS} alerts={[chance]} incidents={[]} axis={axis} />)
    expect(screen.getByText("Argentina: 19% chance to score in the next 10' (usually 13%)")).toBeInTheDocument()
    expect(screen.getByLabelText('By full time')).toHaveTextContent('By full timeArgentina over 2.5 · 63%Over 2.5 · 81%')
    // The model's alerts stand apart from the rules'.
    expect(screen.getByRole('listitem').className).toMatch(/violet/)
  })

  it('leaves items uncoloured until the teams are known', () => {
    render(<MatchFeed teams={null} alerts={[control]} incidents={[]} axis={axis} />)
    expect(screen.getByRole('listitem').className).not.toMatch(/border-(home|away)/)
  })
})
