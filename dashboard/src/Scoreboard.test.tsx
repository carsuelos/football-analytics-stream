import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Scoreboard } from './Scoreboard'
import type { TeamScore } from './schema/engine_status.schema'
import { ARGENTINA, FRANCE, incident, matchInfo, status } from './test/factories'

const TEAMS = [ARGENTINA, FRANCE]

describe('Scoreboard', () => {
  afterEach(() => vi.useRealTimers())

  it('counts the clock on between updates, at the playback speed, not too far, and never back', () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const live = (match_clock_s: number) => status({ state: 'live', period: 1, match_clock_s })
    const clock = () => screen.getByText((_, el) => el?.tagName === 'SPAN' && /^\d+:\d\d/.test(el.textContent ?? '') && el.className.includes('font-mono'))
    const { rerender } = render(<Scoreboard teams={TEAMS} status={live(600)} incidents={[]} connection="open" rate={1.5} />)
    expect(clock()).toHaveTextContent('10:00')
    act(() => vi.advanceTimersByTime(4000))
    expect(clock()).toHaveTextContent('10:06') // 4 s at 1.5×
    act(() => vi.advanceTimersByTime(60_000))
    expect(clock()).toHaveTextContent('10:20') // no further than 20 s past the last update
    rerender(<Scoreboard teams={TEAMS} status={live(615)} incidents={[]} connection="open" rate={1.5} />)
    expect(clock()).toHaveTextContent('10:20') // an update behind what's shown: held, not wound back
    rerender(<Scoreboard teams={TEAMS} status={live(615)} incidents={[]} connection="open" rate={0} />)
    act(() => vi.advanceTimersByTime(10_000))
    expect(clock()).toHaveTextContent('10:20') // paused
  })

  it('waits for kick-off', () => {
    render(<Scoreboard teams={TEAMS} status={null} incidents={[]} connection="open" />)
    expect(screen.getByRole('region', { name: 'Scoreboard' })).toHaveTextContent('Score: Argentina 0, France 0')
    expect(screen.getByRole('region', { name: 'Scoreboard' })).toHaveTextContent('Kick-off soon')
  })

  it('shows the score, the clock to the second and the competition', () => {
    const score: [TeamScore, TeamScore] = [
      { team_id: FRANCE.id, goals: 0 },
      { team_id: ARGENTINA.id, goals: 2 },
    ]
    render(
      <Scoreboard
        teams={TEAMS}
        status={status({ state: 'live', period: 1, match_clock_s: 2214.6, score })}
        incidents={[incident()]}
        connection="open"
        info={matchInfo()}
      />,
    )
    const board = screen.getByRole('region', { name: 'Scoreboard' })
    expect(board).toHaveTextContent('Score: Argentina 2, France 0')
    expect(board).toHaveTextContent('Match clock: 36:541st half')
    expect(board).toHaveTextContent('FIFA World Cup · Final')
    expect(board).toHaveTextContent('LIVE')
    expect(screen.getByRole('list', { name: 'Argentina goals and red cards' })).toHaveTextContent("Di María 35'")
  })

  it('shows stoppage time, the shootout, penalties, own goals and full time', () => {
    const score: [TeamScore, TeamScore] = [
      { team_id: ARGENTINA.id, goals: 3, shootout: 4 },
      { team_id: FRANCE.id, goals: 3, shootout: 2 },
    ]
    render(
      <Scoreboard
        teams={TEAMS}
        status={status({ state: 'ended', period: 2, match_clock_s: 98 * 60 + 5, score })}
        incidents={[
          incident({ id: 'p', kind: 'penalty_goal', player: { id: 1, name: 'Lionel Messi' }, match_clock_s: 23 * 60 }),
          incident({ id: 'o', kind: 'own_goal', team_id: FRANCE.id, player: { id: 2, name: 'Enzo Fernández' }, period: 2, match_clock_s: 77 * 60 }),
        ]}
        connection="open"
      />,
    )
    const board = screen.getByRole('region', { name: 'Scoreboard' })
    expect(board).toHaveTextContent('Match clock: 90+8:052nd half')
    expect(board).toHaveTextContent('4–2 on penalties')
    expect(board).toHaveTextContent('Full time')
    expect(screen.getByRole('list', { name: 'Argentina goals and red cards' })).toHaveTextContent("Messi 23' (pen)")
    expect(screen.getByRole('list', { name: 'France goals and red cards' })).toHaveTextContent("Fernández 77' (og)")
  })

  it('strikes through a goal disallowed after a review, and takes it off the score', () => {
    const goal = incident({ id: 'g' })
    const var_ = incident({
      id: 'v',
      kind: 'goal_disallowed',
      cancels: 'g',
      reason: 'offside',
      score: [
        { team_id: ARGENTINA.id, goals: 1 },
        { team_id: FRANCE.id, goals: 0 },
      ],
    })
    render(<Scoreboard teams={TEAMS} status={status({ score: undefined })} incidents={[goal, var_]} connection="open" />)
    expect(screen.getByRole('region', { name: 'Scoreboard' })).toHaveTextContent('Score: Argentina 1, France 0')
    const line = screen.getByRole('list', { name: 'Argentina goals and red cards' })
    expect(line).toHaveTextContent('VAR')
    expect(screen.getByText("Di María 35'")).toHaveClass('line-through')
  })
})
