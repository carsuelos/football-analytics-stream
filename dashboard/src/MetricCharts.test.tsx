import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { MetricCharts } from './MetricCharts'
import { alert, ARGENTINA, FRANCE, snapshot } from './test/factories'

const TEAMS = [ARGENTINA, FRANCE]

describe('MetricCharts', () => {
  it('asks for a match until the teams are known', () => {
    render(<MetricCharts teams={null} snapshots={[]} alerts={[]} />)
    expect(screen.getByText('No match yet. Choose one above.')).toBeInTheDocument()
    expect(screen.queryByRole('figure')).toBeNull()
  })

  it('says when the broadcast is paused before the first metrics', () => {
    render(<MetricCharts teams={TEAMS} snapshots={[]} alerts={[]} broadcastState="paused" />)
    expect(screen.getByText('The broadcast is paused. Press Play under Broadcast to start it.')).toBeInTheDocument()
  })

  it('waits for the first metrics in the chosen window', async () => {
    render(<MetricCharts teams={TEAMS} snapshots={[snapshot(1, 600, 600)]} alerts={[]} />)
    expect(screen.getByText('Waiting for the first metrics (one every 30 seconds of play)…')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: "10'" }))
    expect(screen.getAllByRole('figure').map((f) => f.getAttribute('aria-label'))).toEqual([
      'Field tilt',
      'xT added',
      'Pressure index',
    ])
  })

  it("shows the teams and a 5' window by default", () => {
    render(<MetricCharts teams={TEAMS} snapshots={[snapshot(1, 300), snapshot(1, 600)]} alerts={[alert({ period: 1, match_clock_s: 550 })]} />)
    expect(screen.getByRole('list', { name: 'Teams' })).toHaveTextContent(/Argentina\s*France/)
    expect(screen.getByRole('button', { name: "5'" })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: "10'" })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getAllByRole('figure')).toHaveLength(3)
  })
})
