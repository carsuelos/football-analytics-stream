import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, sendViewer } from './api'
import type { EngineStatus } from './schema/engine_status.schema'
import { deferred, status } from './test/factories'
import { useViewer } from './useViewer'

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  sendViewer: vi.fn(),
}))

afterEach(() => {
  vi.resetAllMocks()
})

describe('useViewer', () => {
  it('is pending while a command is in flight', async () => {
    const reply = deferred<EngineStatus>()
    vi.mocked(sendViewer).mockReturnValue(reply.promise)
    const { result } = renderHook(() => useViewer())
    let sent: Promise<void> | undefined
    act(() => {
      sent = result.current.send({ command: 'pause' })
    })
    expect(sendViewer).toHaveBeenCalledWith({ command: 'pause' })
    expect(result.current.pending).toBe(true)
    await act(async () => {
      reply.resolve(status({ state: 'paused' }))
      await sent
    })
    expect(result.current).toMatchObject({ pending: false, error: null })
  })

  it('shows an error until the next command succeeds', async () => {
    vi.mocked(sendViewer).mockRejectedValueOnce(new ApiError('no match yet', 409))
    const { result } = renderHook(() => useViewer())
    await act(() => result.current.send({ command: 'go_live' }))
    expect(result.current).toMatchObject({ pending: false, error: 'no match yet' })

    vi.mocked(sendViewer).mockResolvedValueOnce(status())
    await act(() => result.current.send({ command: 'go_live' }))
    expect(result.current.error).toBeNull()
  })
})
