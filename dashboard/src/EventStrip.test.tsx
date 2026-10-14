import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { EventStrip } from './EventStrip'
import { lanes } from './lanes'
import { alert, ARGENTINA, FRANCE, incident } from './test/factories'
import { timeline } from './timeline'

describe('EventStrip', () => {
  it('places events and alerts along the match, each described on hover or focus', () => {
    const axis = timeline([])
    render(
      <EventStrip
        teams={[ARGENTINA, FRANCE]}
        incidents={[incident(), incident({ id: 's', kind: 'shootout_goal', period: 5, match_clock_s: 7200 })]}
        alerts={[alert({ team_id: ARGENTINA.id, period: 1, match_clock_s: 35 * 60, message: 'Argentina in control' })]}
        axis={axis}
        now={45}
      />,
    )
    const events = screen.getByRole('list', { name: 'Events' })
    const [goal] = within(events).getAllByRole('button')
    expect(within(events).getAllByRole('button')).toHaveLength(1) // not the shootout
    expect(goal).toHaveAccessibleName('35:22 · Goal · Ángel Di María · 2–0')
    expect(goal.closest('li')).toHaveStyle({ left: `${(2122.5 / 60 / 90) * 100}%` })
    const [a] = within(screen.getByRole('list', { name: 'Alerts' })).getAllByRole('button')
    expect(a).toHaveAccessibleName('35:00 · Control · Argentina in control')
    expect(screen.getAllByRole('tooltip', { hidden: true }).map((t) => t.textContent)).toContain('35:00 · Control · Argentina in control')
  })
})

describe('lanes', () => {
  it('stacks markers that are close together, up to three lanes', () => {
    expect(lanes([0.5, 0.1, 0.51, 0.52, 0.525, 0.9], 0.03)).toEqual([0, 0, 1, 2, 2, 0])
    expect(lanes([0.1, 0.2, 0.3], 0.03)).toEqual([0, 0, 0])
  })
})
