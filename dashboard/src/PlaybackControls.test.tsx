import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { PlaybackControls } from './PlaybackControls'
import type { PlaybackStatus } from './schema/status.schema'
import { playback } from './test/factories'

function renderControls(status: PlaybackStatus | null, disabled = false) {
  const onCommand = vi.fn()
  render(<PlaybackControls status={status} disabled={disabled} onCommand={onCommand} />)
  return onCommand
}

const controls = () => [
  ...screen.getAllByRole('button'),
  screen.getByRole('combobox', { name: 'Period' }),
  screen.getByRole('spinbutton', { name: 'Minute' }),
]

describe('PlaybackControls', () => {
  it('plays when paused', async () => {
    const onCommand = renderControls(playback({ state: 'paused' }))
    await userEvent.click(screen.getByRole('button', { name: 'Play' }))
    expect(onCommand).toHaveBeenCalledWith({ command: 'play' })
  })

  it('pauses when playing', async () => {
    const onCommand = renderControls(playback({ state: 'playing' }))
    await userEvent.click(screen.getByRole('button', { name: 'Pause' }))
    expect(onCommand).toHaveBeenCalledWith({ command: 'pause' })
  })

  it('shows the current speed and sets another', async () => {
    const onCommand = renderControls(playback({ speed: 10 }))
    expect(screen.getByRole('button', { name: '10×' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '60×' })).toHaveAttribute('aria-pressed', 'false')

    await userEvent.click(screen.getByRole('button', { name: '60×' }))
    expect(onCommand).toHaveBeenCalledWith({ command: 'set_speed', speed: 60 })
  })

  it('seeks to a minute within the chosen period, starting from the period start', async () => {
    const onCommand = renderControls(playback())
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Period' }), '2nd half')
    const minute = screen.getByRole('spinbutton', { name: 'Minute' })
    expect(minute).toHaveValue(45)

    await userEvent.clear(minute)
    await userEvent.type(minute, '82')
    await userEvent.click(screen.getByRole('button', { name: 'Go' }))
    expect(onCommand).toHaveBeenCalledWith({ command: 'seek', seek_to: { period: 2, match_clock_s: 4920 } })
  })

  it.each(['', '-5'])('does not seek to minute %j', async (value) => {
    const onCommand = renderControls(playback())
    const minute = screen.getByRole('spinbutton', { name: 'Minute' })
    await userEvent.clear(minute)
    if (value) await userEvent.type(minute, value)
    await userEvent.click(screen.getByRole('button', { name: 'Go' }))
    expect(onCommand).not.toHaveBeenCalled()
  })

  it.each([
    ['before the status arrives', null],
    ['with no match loaded', playback({ state: 'idle', match_id: undefined })],
  ])('is disabled %s', (_, status) => {
    renderControls(status)
    for (const control of controls()) {
      expect(control).toBeDisabled()
    }
  })

  it('is disabled while a command is pending', () => {
    renderControls(playback(), true)
    for (const control of controls()) {
      expect(control).toBeDisabled()
    }
  })

  it('cannot play an ended match, but can still seek back into it', () => {
    renderControls(playback({ state: 'ended' }))
    expect(screen.getByRole('button', { name: 'Play' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '1×' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Go' })).toBeEnabled()
  })
})
