import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AlertFeed } from './AlertFeed'
import { alert, ARGENTINA, FRANCE } from './test/factories'

const TEAMS = [ARGENTINA, FRANCE]

describe('AlertFeed', () => {
  it('says when there are no alerts', () => {
    render(<AlertFeed teams={TEAMS} alerts={[]} />)
    expect(screen.getByText('No alerts yet.')).toBeInTheDocument()
    expect(screen.queryByRole('list')).toBeNull()
  })

  it('lists alerts latest in the match first, with their minute and type', () => {
    render(
      <AlertFeed
        teams={TEAMS}
        alerts={[
          alert({ id: 'a', period: 2, match_clock_s: 82 * 60, message: 'France taking control' }),
          alert({ id: 'b', period: 1, match_clock_s: 47 * 60, type: 'goal_threat', team_id: ARGENTINA.id, message: 'Argentina goal threat' }),
          alert({ id: 'c', period: 2, match_clock_s: 46 * 60, type: 'momentum_shift', message: 'France momentum' }),
        ]}
      />,
    )
    const items = screen.getAllByRole('listitem')
    expect(items.map((li) => li.textContent)).toEqual([
      "82' · Control shiftFrance taking control",
      "46' · MomentumFrance momentum",
      "45+2' · Goal threatArgentina goal threat",
    ])
    expect(items.map((li) => li.className.match(/border-(home|away)/)?.[1])).toEqual(['away', 'away', 'home'])
  })

  it('leaves alerts uncoloured until the teams are known', () => {
    render(<AlertFeed teams={null} alerts={[alert()]} />)
    expect(screen.getByRole('listitem').className).not.toMatch(/border-(home|away)/)
  })
})
