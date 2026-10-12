import { describe, expect, it } from 'vitest'
import { initialMatchState, matchReducer, type MatchState, type StreamEvent } from './matchState'
import { alert, reset, snapshot, status } from './test/factories'

const apply = (...events: StreamEvent[]): MatchState => events.reduce(matchReducer, initialMatchState)

describe('matchReducer', () => {
  it('starts out connecting, with no match', () => {
    expect(initialMatchState).toEqual({ connection: 'connecting', reset: null, status: null, snapshots: [], alerts: [] })
  })

  it('builds the match from a reset, the latest status and the history', () => {
    const s1 = snapshot(1, 30)
    const s2 = snapshot(1, 60)
    const a = alert()
    const state = apply(
      { type: 'open' },
      { type: 'reset', data: reset(2) },
      { type: 'status', data: status({ released: 1 }) },
      { type: 'snapshot', data: s1 },
      { type: 'alert', data: a },
      { type: 'snapshot', data: s2 },
      { type: 'status', data: status({ released: 2 }) },
    )
    expect(state).toEqual({
      connection: 'open',
      reset: reset(2),
      status: status({ released: 2 }),
      snapshots: [s1, s2],
      alerts: [a],
    })
  })

  it('starts over on a reset', () => {
    const state = apply(
      { type: 'reset', data: reset(1) },
      { type: 'status', data: status() },
      { type: 'snapshot', data: snapshot(1, 30) },
      { type: 'alert', data: alert() },
      { type: 'reset', data: reset(2) },
    )
    expect(state).toEqual({ ...initialMatchState, reset: reset(2) })
  })

  it('keeps the match on screen while the connection is lost', () => {
    const before = apply({ type: 'open' }, { type: 'reset', data: reset() }, { type: 'snapshot', data: snapshot(1, 30) })
    expect(matchReducer(before, { type: 'lost' })).toEqual({ ...before, connection: 'lost' })
  })

  it('does not modify the previous state', () => {
    const before = apply({ type: 'reset', data: reset() }, { type: 'snapshot', data: snapshot(1, 30) })
    const copy = structuredClone(before)
    matchReducer(before, { type: 'snapshot', data: snapshot(1, 60) })
    matchReducer(before, { type: 'alert', data: alert() })
    expect(before).toEqual(copy)
  })
})
