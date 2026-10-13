import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getMatches, getPlayback, sendCommand } from './api'
import type { EngineState } from './schema/engine_status.schema'
import type { PlaybackStatus } from './schema/status.schema'
import { deferred, matchInfo, playback } from './test/factories'
import { usePlayback } from './usePlayback'

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  getMatches: vi.fn(),
  getPlayback: vi.fn(),
  sendCommand: vi.fn(),
}))

const MATCHES = { schema_version: 1 as const, matches: [matchInfo()] }

beforeEach(() => {
  vi.mocked(getMatches).mockResolvedValue(MATCHES)
  vi.mocked(getPlayback).mockResolvedValue(playback())
})

afterEach(() => {
  vi.resetAllMocks()
})

const renderPlayback = (state?: EngineState) =>
  renderHook(({ state }: { state?: EngineState }) => usePlayback(state), { initialProps: { state } })

describe('usePlayback', () => {
  it('fetches the matches and the playback status on load', async () => {
    const { result } = renderPlayback()
    expect(result.current.matches).toBeNull()
    await waitFor(() => expect(result.current.status).toEqual(playback()))
    expect(result.current.matches).toEqual(MATCHES.matches)
    expect(result.current.error).toBeNull()
  })

  it('takes the status from the command reply, and is pending meanwhile', async () => {
    const reply = deferred<PlaybackStatus>()
    vi.mocked(sendCommand).mockReturnValue(reply.promise)
    const { result } = renderPlayback()
    await waitFor(() => expect(result.current.status).not.toBeNull())

    let sent!: Promise<void>
    act(() => {
      sent = result.current.send({ command: 'play' })
    })
    expect(sendCommand).toHaveBeenCalledWith({ command: 'play' })
    expect(result.current.pending).toBe(true)

    await act(async () => {
      reply.resolve(playback({ state: 'playing' }))
      await sent
    })
    expect(result.current.status?.state).toBe('playing')
    expect(result.current.pending).toBe(false)
  })

  it('shows a failed command and keeps the last status, until the next success', async () => {
    vi.mocked(sendCommand).mockRejectedValueOnce(new ApiError('no match loaded', 409))
    const { result } = renderPlayback()
    await waitFor(() => expect(result.current.status).not.toBeNull())

    await act(() => result.current.send({ command: 'play' }))
    expect(result.current.error).toBe('no match loaded')
    expect(result.current.status).toEqual(playback())
    expect(result.current.pending).toBe(false)

    vi.mocked(sendCommand).mockResolvedValueOnce(playback({ state: 'playing' }))
    await act(() => result.current.send({ command: 'play' }))
    expect(result.current.error).toBeNull()
  })

  it('refetches the status when the engine state changes', async () => {
    const { result, rerender } = renderPlayback('live')
    await waitFor(() => expect(result.current.status).not.toBeNull())
    expect(getPlayback).toHaveBeenCalledTimes(1)

    vi.mocked(getPlayback).mockResolvedValue(playback({ state: 'ended' }))
    rerender({ state: 'ended' })
    await waitFor(() => expect(result.current.status?.state).toBe('ended'))
    expect(getPlayback).toHaveBeenCalledTimes(2)
    // The match list doesn't change, so once fetched it isn't fetched again.
    expect(getMatches).toHaveBeenCalledTimes(1)
  })

  it('shows a failed match list, and retries it on the next engine state change', async () => {
    vi.mocked(getMatches).mockRejectedValueOnce(new ApiError('simulator unavailable', 502))
    const { result, rerender } = renderPlayback()
    await waitFor(() => expect(result.current.error).toBe('simulator unavailable'))
    expect(result.current.matches).toBeNull()

    rerender({ state: 'waiting' })
    await waitFor(() => expect(result.current.matches).toEqual(MATCHES.matches))
  })

  it.each([
    ['reply', (slow: ReturnType<typeof deferred<PlaybackStatus>>) => slow.resolve(playback({ state: 'paused' }))],
    ['failure', (slow: ReturnType<typeof deferred<PlaybackStatus>>) => slow.reject(new ApiError('engine unavailable', 502))],
  ])('ignores a %s that a later request has overtaken', async (_, settle) => {
    const slowFetch = deferred<PlaybackStatus>()
    vi.mocked(getPlayback).mockReturnValue(slowFetch.promise)
    vi.mocked(sendCommand).mockResolvedValue(playback({ state: 'playing' }))
    const { result } = renderPlayback()

    await act(() => result.current.send({ command: 'play' }))
    await act(async () => settle(slowFetch))
    expect(result.current.status?.state).toBe('playing')
    expect(result.current.error).toBeNull()
  })
})
