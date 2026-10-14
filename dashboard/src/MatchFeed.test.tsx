import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { MatchFeed } from './MatchFeed'
import { alert, ARGENTINA, FRANCE, incident } from './test/factories'
import { timeline } from './timeline'

const TEAMS = [ARGENTINA, FRANCE]
const axis = timeline([])

const control = alert({ id: 'a', team_id: ARGENTINA.id, period: 1, match_clock_s: 35 * 60, message: 'Argentina in control' })
const threat = alert({ id: 'b', type: 'goal_threat', team_id: FRANCE.id, period: 1, match_clock_s: 20 * 60, message: 'France goal threat 20%' })
const goal = incident()

describe('MatchFeed', () => {
  it('says when there is nothing yet', () => {
    render(<MatchFeed teams={TEAMS} alerts={[]} incidents={[]} axis={axis} />)
    expect(screen.getByText('Nothing yet.')).toBeInTheDocument()
  })

  it('lists events and alerts latest first, to the second, and marks the alerts that came true', () => {
    render(<MatchFeed teams={TEAMS} alerts={[control, threat]} incidents={[goal]} axis={axis} now={40} />)
    const items = screen.getAllByRole('listitem')
    expect(items.map((li) => li.textContent)).toEqual([
      '35:22· Argentina2–0Goal · Ángel Di María',
      '35:00· Control Scored 23s laterArgentina in control',
      "20:00· Goal threatNo goal in 10'France goal threat 20%",
    ])
    expect(items.map((li) => li.className.match(/border-(home|away)/)?.[1])).toEqual(['home', 'home', 'away'])
  })

  it('filters to events or alerts', async () => {
    render(<MatchFeed teams={TEAMS} alerts={[control]} incidents={[goal]} axis={axis} />)
    await userEvent.click(screen.getByRole('button', { name: 'Events' }))
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    expect(screen.getByRole('listitem')).toHaveTextContent('Goal · Ángel Di María')
    await userEvent.click(screen.getByRole('button', { name: 'Alerts' }))
    expect(screen.getByRole('listitem')).toHaveTextContent('Argentina in control')
  })

  it('shows a disallowed goal struck through, and an alert before it unscored', () => {
    const var_ = incident({ id: 'v', kind: 'goal_disallowed', cancels: goal.id, reason: 'offside', match_clock_s: 36 * 60 })
    render(<MatchFeed teams={TEAMS} alerts={[control]} incidents={[goal, var_]} axis={axis} />)
    expect(screen.getByText('Disallowed after review')).toBeInTheDocument()
    expect(screen.getByText('Goal disallowed (offside) · Ángel Di María')).toBeInTheDocument()
    expect(screen.queryByText(/Scored/)).toBeNull()
  })

  it('leaves items uncoloured until the teams are known', () => {
    render(<MatchFeed teams={null} alerts={[control]} incidents={[]} axis={axis} />)
    expect(screen.getByRole('listitem').className).not.toMatch(/border-(home|away)/)
  })
})
