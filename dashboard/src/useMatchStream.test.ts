import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RETRY_MS, useMatchStream } from './useMatchStream'
import { alert, reset, snapshot, status } from './test/factories'

/** Stands in for the browser's EventSource, which jsdom does not have. */
class FakeEventSource extends EventTarget {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 2
  static instances: FakeEventSource[] = []

  readyState = FakeEventSource.CONNECTING
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  readonly url: string

  constructor(url: string) {
    super()
    this.url = url
    FakeEventSource.instances.push(this)
  }

  open() {
    this.readyState = FakeEventSource.OPEN
    this.onopen?.()
  }

  send(type: string, data: unknown) {
    this.dispatchEvent(new MessageEvent(type, { data: JSON.stringify(data) }))
  }

  /** Fails like a dropped connection (the browser retries) or an error reply (it gives up). */
  fail(givesUp: boolean) {
    this.readyState = givesUp ? FakeEventSource.CLOSED : FakeEventSource.CONNECTING
    this.onerror?.()
  }

  close() {
    this.readyState = FakeEventSource.CLOSED
  }
}

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
    act(() => {
      latest().open()
      latest().send('reset', reset())
      latest().send('status', status())
      latest().send('snapshot', s)
      latest().send('alert', a)
    })
    expect(result.current).toEqual({ connection: 'open', reset: reset(), status: status(), snapshots: [s], alerts: [a] })
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
    expect(result.current).toMatchObject({ connection: 'open', reset: reset(2) })
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
