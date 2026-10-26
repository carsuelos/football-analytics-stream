import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { marks } from './chartMarks'
import { MetricCharts } from './MetricCharts'
import { alert, ARGENTINA, FRANCE, incident, snapshot } from './test/factories'
import { timeline } from './timeline'

const TEAMS = [ARGENTINA, FRANCE]
const axis = timeline([])

describe('MetricCharts', () => {
  it('asks for a match until the teams are known', () => {
    render(<MetricCharts teams={null} snapshots={[]} alerts={[]} axis={axis} />)
    expect(screen.getByText('No match yet. Choose one in the Replay panel.')).toBeInTheDocument()
    expect(screen.queryByRole('figure')).toBeNull()
  })

  it('says when the broadcast is paused before the first metrics', () => {
    render(<MetricCharts teams={TEAMS} snapshots={[]} alerts={[]} axis={axis} broadcastState="paused" />)
    expect(screen.getByText('The broadcast is paused. Press Play in the Replay panel to start it.')).toBeInTheDocument()
  })

  it('waits for the feed instead when there is no simulator', () => {
    const { rerender } = render(<MetricCharts teams={null} snapshots={[]} alerts={[]} axis={axis} simulator={false} />)
    expect(screen.getByText('No match yet. Waiting for the feed to start one…')).toBeInTheDocument()
    rerender(<MetricCharts teams={TEAMS} snapshots={[]} alerts={[]} axis={axis} broadcastState="paused" simulator={false} />)
    expect(screen.getByText('Waiting for the first metrics (one every 5 seconds of play)…')).toBeInTheDocument()
  })

  it('waits for the first metrics in the chosen window', async () => {
    render(<MetricCharts teams={TEAMS} snapshots={[snapshot(1, 600, 600)]} alerts={[]} axis={axis} />)
    expect(screen.getByText('Waiting for the first metrics (one every 5 seconds of play)…')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: "10'" }))
    expect(screen.getAllByRole('figure').map((f) => f.getAttribute('aria-label'))).toEqual(['Field tilt', 'xT added', 'Pressure index'])
  })

  it("shows the teams, the latest values head to head and a 5' window by default", () => {
    render(
      <MetricCharts
        teams={TEAMS}
        snapshots={[snapshot(1, 300), snapshot(1, 600, 300, [12, 4])]}
        alerts={[alert({ period: 1, match_clock_s: 550 })]}
        axis={axis}
      />,
    )
    expect(screen.getByRole('list', { name: 'Teams' })).toHaveTextContent(/Argentina\s*France/)
    expect(screen.getByRole('button', { name: "5'" })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: "10'" })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getAllByRole('figure')).toHaveLength(3)
    expect(screen.getByLabelText('Head to head')).toHaveTextContent('Pressure' + 'Argentina 12.0France 4.0')
  })

  it('marks goals, disallowed goals, red cards and alerts, each described', () => {
    const goal = incident({ id: 'g1' })
    const all = marks(
      [alert({ id: 'a', period: 1, match_clock_s: 35 * 60, team_id: ARGENTINA.id, type: 'control_shift', message: 'Argentina in control' })],
      [
        goal,
        incident({ id: 'g2', match_clock_s: 40 * 60 }),
        incident({ id: 'v', kind: 'goal_disallowed', match_clock_s: 41 * 60, cancels: 'g2', reason: 'offside' }),
        incident({ id: 'r', kind: 'red_card', team_id: FRANCE.id, period: 2, match_clock_s: 50 * 60, player: { id: 1, name: 'X' } }),
        incident({ id: 'y', kind: 'yellow_card', match_clock_s: 51 * 60 }),
        incident({ id: 's', kind: 'shootout_goal', period: 5, match_clock_s: 7200 }),
      ],
      TEAMS,
      axis,
    )
    expect(all.map((m) => [m.id, m.shape, m.title])).toEqual([
      ['a', 'alert', "35:00 · Control · Argentina in control"],
      ['g1', 'goal', '35:22 · Goal · Ángel Di María'],
      ['g2', 'disallowed', '40:00 · Goal · Ángel Di María (disallowed)'],
      ['r', 'card', '50:00 · Red card · X'],
    ])
  })
})
