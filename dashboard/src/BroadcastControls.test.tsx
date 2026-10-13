import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { BroadcastControls } from './BroadcastControls'
import type { BroadcastStatus } from './schema/broadcast_status.schema'
import { broadcast } from './test/factories'

function renderControls(status: BroadcastStatus | null, disabled = false) {
  const onCommand = vi.fn()
  render(<BroadcastControls status={status} disabled={disabled} onCommand={onCommand} />)
  return onCommand
}

const controls = () => screen.getAllByRole('button')

describe('BroadcastControls', () => {
  it('plays when paused', async () => {
    const onCommand = renderControls(broadcast({ state: 'paused' }))
    await userEvent.click(screen.getByRole('button', { name: 'Play' }))
    expect(onCommand).toHaveBeenCalledWith({ command: 'play' })
  })

  it('pauses when playing', async () => {
    const onCommand = renderControls(broadcast({ state: 'playing' }))
    await userEvent.click(screen.getByRole('button', { name: 'Pause' }))
    expect(onCommand).toHaveBeenCalledWith({ command: 'pause' })
  })

  it('shows the current speed and sets another', async () => {
    const onCommand = renderControls(broadcast({ speed: 10 }))
    expect(screen.getByRole('button', { name: '10×' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '60×' })).toHaveAttribute('aria-pressed', 'false')

    await userEvent.click(screen.getByRole('button', { name: '60×' }))
    expect(onCommand).toHaveBeenCalledWith({ command: 'set_speed', speed: 60 })
  })

  it.each([
    ['before the status arrives', null],
    ['with no match loaded', broadcast({ state: 'idle', match_id: undefined })],
  ])('is disabled %s', (_, status) => {
    renderControls(status)
    for (const control of controls()) {
      expect(control).toBeDisabled()
    }
  })

  it('is disabled while a command is pending', () => {
    renderControls(broadcast(), true)
    for (const control of controls()) {
      expect(control).toBeDisabled()
    }
  })

  it('cannot play an ended match', () => {
    renderControls(broadcast({ state: 'ended' }))
    expect(screen.getByRole('button', { name: 'Play' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '1×' })).toBeEnabled()
  })
})
