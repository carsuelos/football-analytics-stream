import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getMatches, getBroadcast, sendBroadcast } from './api'
import type { EngineState } from './schema/engine_status.schema'
import type { BroadcastStatus } from './schema/broadcast_status.schema'
import { deferred, matchInfo, broadcast } from './test/factories'
import { useBroadcast } from './useBroadcast'

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  getMatches: vi.fn(),
  getBroadcast: vi.fn(),
  sendBroadcast: vi.fn(),
}))

const MATCHES = { schema_version: 1 as const, matches: [matchInfo()] }

beforeEach(() => {
  vi.mocked(getMatches).mockResolvedValue(MATCHES)
  vi.mocked(getBroadcast).mockResolvedValue(broadcast())
})

afterEach(() => {
  vi.resetAllMocks()
})

const renderBroadcast = (state?: EngineState) =>
  renderHook(({ state }: { state?: EngineState }) => useBroadcast(state), { initialProps: { state } })

describe('useBroadcast', () => {
  it('fetches the matches and the broadcast status on load', async () => {
    const { result } = renderBroadcast()
    expect(result.current.matches).toBeNull()
    await waitFor(() => expect(result.current.status).toEqual(broadcast()))
    expect(result.current.matches).toEqual(MATCHES.matches)
    expect(result.current.error).toBeNull()
  })

  it('takes the status from the command reply, and is pending meanwhile', async () => {
    const reply = deferred<BroadcastStatus>()
    vi.mocked(sendBroadcast).mockReturnValue(reply.promise)
    const { result } = renderBroadcast()
    await waitFor(() => expect(result.current.status).not.toBeNull())

    let sent!: Promise<boolean>
    act(() => {
      sent = result.current.send({ command: 'play' })
    })
    expect(sendBroadcast).toHaveBeenCalledWith({ command: 'play' })
    expect(result.current.pending).toBe(true)

    await act(async () => {
      reply.resolve(broadcast({ state: 'playing' }))
      expect(await sent).toBe(true)
    })
    expect(result.current.status?.state).toBe('playing')
    expect(result.current.pending).toBe(false)
  })

  it('shows a failed command and keeps the last status, until the next success', async () => {
    vi.mocked(sendBroadcast).mockRejectedValueOnce(new ApiError('no match loaded', 409))
    const { result } = renderBroadcast()
    await waitFor(() => expect(result.current.status).not.toBeNull())

    let ok = true
    await act(async () => {
      ok = await result.current.send({ command: 'play' })
    })
    expect(ok).toBe(false)
    expect(result.current.error).toBe('no match loaded')
    expect(result.current.status).toEqual(broadcast())
    expect(result.current.pending).toBe(false)

    vi.mocked(sendBroadcast).mockResolvedValueOnce(broadcast({ state: 'playing' }))
    await act(() => result.current.send({ command: 'play' }))
    expect(result.current.error).toBeNull()
  })

  it('refetches the status when the engine state changes', async () => {
    const { result, rerender } = renderBroadcast('live')
    await waitFor(() => expect(result.current.status).not.toBeNull())
    expect(getBroadcast).toHaveBeenCalledTimes(1)

    vi.mocked(getBroadcast).mockResolvedValue(broadcast({ state: 'ended' }))
    rerender({ state: 'ended' })
    await waitFor(() => expect(result.current.status?.state).toBe('ended'))
    expect(getBroadcast).toHaveBeenCalledTimes(2)
    // The match list doesn't change, so once fetched it isn't fetched again.
    expect(getMatches).toHaveBeenCalledTimes(1)
  })

  it('shows a failed match list, and retries it on the next engine state change', async () => {
    vi.mocked(getMatches).mockRejectedValueOnce(new ApiError('simulator unavailable', 502))
    const { result, rerender } = renderBroadcast()
    await waitFor(() => expect(result.current.error).toBe('simulator unavailable'))
    expect(result.current.matches).toBeNull()

    rerender({ state: 'waiting' })
    await waitFor(() => expect(result.current.matches).toEqual(MATCHES.matches))
  })

  it.each([
    ['reply', (slow: ReturnType<typeof deferred<BroadcastStatus>>) => slow.resolve(broadcast({ state: 'paused' }))],
    ['failure', (slow: ReturnType<typeof deferred<BroadcastStatus>>) => slow.reject(new ApiError('engine unavailable', 502))],
  ])('ignores a %s that a later request has overtaken', async (_, settle) => {
    const slowFetch = deferred<BroadcastStatus>()
    vi.mocked(getBroadcast).mockReturnValue(slowFetch.promise)
    vi.mocked(sendBroadcast).mockResolvedValue(broadcast({ state: 'playing' }))
    const { result } = renderBroadcast()

    await act(() => result.current.send({ command: 'play' }))
    await act(async () => settle(slowFetch))
    expect(result.current.status?.state).toBe('playing')
    expect(result.current.error).toBeNull()
  })
})
