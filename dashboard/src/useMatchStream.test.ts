import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FLUSH_MS, RETRY_MS, useMatchStream } from './useMatchStream'
import { alert, incident, reset, snapshot, status } from './test/factories'
import { FakeEventSource } from './test/fakeEventSource'

const latest = () => FakeEventSource.instances.at(-1)!

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useMatchStream', () => {
  it('builds the match state from the stream', () => {
    const { result } = renderHook(() => useMatchStream())
    expect(latest().url).toBe('/api/stream')
    expect(result.current.connection).toBe('connecting')

    const s = snapshot(1, 30)
    const a = alert()
    const i = incident()
    act(() => {
      latest().open()
      latest().send('reset', reset())
      latest().send('status', status())
      latest().send('snapshot', s)
      latest().send('alert', a)
      latest().send('incident', i)
    })
    // Messages are applied together, a moment later.
    expect(result.current.snapshots).toEqual([])
    act(() => vi.advanceTimersByTime(FLUSH_MS))
    expect(result.current).toEqual({ connection: 'open', reset: reset(), status: status(), snapshots: [s], alerts: [a], incidents: [i] })
  })

  it('lets the browser reconnect after a dropped connection', () => {
    const { result } = renderHook(() => useMatchStream())
    act(() => latest().open())
    act(() => latest().fail(false))
    expect(result.current.connection).toBe('lost')
    act(() => vi.advanceTimersByTime(RETRY_MS * 2))
    expect(FakeEventSource.instances).toHaveLength(1)
    act(() => latest().open())
    expect(result.current.connection).toBe('open')
  })

  it('reconnects itself after the browser gives up', () => {
    const { result } = renderHook(() => useMatchStream())
    const first = latest()
    act(() => first.fail(true))
    expect(result.current.connection).toBe('lost')
    act(() => vi.advanceTimersByTime(RETRY_MS - 1))
    expect(FakeEventSource.instances).toHaveLength(1)
    act(() => vi.advanceTimersByTime(1))
    expect(FakeEventSource.instances).toHaveLength(2)

    act(() => {
      latest().open()
      latest().send('reset', reset(2))
    })
    act(() => vi.advanceTimersByTime(FLUSH_MS))
    expect(result.current).toMatchObject({ connection: 'open', reset: reset(2) })
  })

  it('applies what arrived before the connection dropped first', () => {
    const { result } = renderHook(() => useMatchStream())
    act(() => {
      latest().open()
      latest().send('reset', reset(3))
      latest().fail(false)
    })
    expect(result.current).toMatchObject({ connection: 'lost', reset: reset(3) })
  })

  it('closes the stream and cancels a pending retry on unmount', () => {
    const { unmount } = renderHook(() => useMatchStream())
    const first = latest()
    act(() => first.fail(true))
    unmount()
    act(() => vi.advanceTimersByTime(RETRY_MS * 2))
    expect(FakeEventSource.instances).toHaveLength(1)

    const { unmount: unmount2 } = renderHook(() => useMatchStream())
    const second = latest()
    unmount2()
    expect(second.readyState).toBe(FakeEventSource.CLOSED)
  })
})
