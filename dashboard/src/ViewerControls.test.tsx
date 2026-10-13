import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { EngineStatus, LiveEdge } from './schema/engine_status.schema'
import { status } from './test/factories'
import { ViewerControls } from './ViewerControls'

const EDGE: LiveEdge = { offset: 2500, period: 2, match_clock_s: 82 * 60 + 30, play_s: 5000 }

const viewer = (overrides: Partial<EngineStatus> = {}) =>
  status({ state: 'live', speed: 1, live_edge: EDGE, behind_live_s: 0, ...overrides })

function renderControls(s: EngineStatus | null, disabled = false) {
  const onCommand = vi.fn()
  render(<ViewerControls status={s} disabled={disabled} onCommand={onCommand} />)
  return onCommand
}

const controls = () => [
  ...screen.getAllByRole('button'),
  screen.getByRole('combobox', { name: 'Period' }),
  screen.getByRole('spinbutton', { name: 'Minute' }),
]

describe('ViewerControls', () => {
  it('shows it is live, and pauses', async () => {
    const onCommand = renderControls(viewer())
    expect(screen.getByText('LIVE')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Go live' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Pause' }))
    expect(onCommand).toHaveBeenCalledWith({ command: 'pause' })
  })

  it('shows how far behind live it is, plays and goes live', async () => {
    const onCommand = renderControls(viewer({ state: 'paused', behind_live_s: 754.6 }))
    expect(screen.queryByText('LIVE')).not.toBeInTheDocument()
    expect(screen.getByText('12:34 behind live')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Play' }))
    expect(onCommand).toHaveBeenCalledWith({ command: 'play' })
    await userEvent.click(screen.getByRole('button', { name: 'Go live' }))
    expect(onCommand).toHaveBeenCalledWith({ command: 'go_live' })
  })

  it('can go live while playing behind it, or rebuilding after a seek back', () => {
    renderControls(viewer({ state: 'playing', behind_live_s: 30 }))
    expect(screen.getByRole('button', { name: 'Pause' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Go live' })).toBeEnabled()
  })

  it.each([
    ['rebuilding behind live', viewer({ state: 'rebuilding', behind_live_s: 30 }), true],
    ['rebuilding on reconnect', viewer({ state: 'rebuilding', behind_live_s: 0 }), false],
  ])('when %s, go live is enabled: %s', (_, s, enabled) => {
    renderControls(s)
    expect(screen.getByRole('button', { name: 'Go live' })).toHaveProperty('disabled', !enabled)
  })

  it("shows the viewer's speed and sets another", async () => {
    const onCommand = renderControls(viewer({ speed: 10 }))
    expect(screen.getByRole('button', { name: '10×' })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(screen.getByRole('button', { name: '60×' }))
    expect(onCommand).toHaveBeenCalledWith({ command: 'set_speed', speed: 60 })
  })

  it('seeks to a minute within a period, up to the live edge', async () => {
    const onCommand = renderControls(viewer())
    expect(screen.getByText("Live: 82'")).toBeInTheDocument()
    const period = screen.getByRole('combobox', { name: 'Period' })
    expect([...period.querySelectorAll('option')].map((o) => o.textContent)).toEqual(['1st half', '2nd half'])
    await userEvent.selectOptions(period, '2nd half')
    const minute = screen.getByRole('spinbutton', { name: 'Minute' })
    expect(minute).toHaveValue(45)
    expect(minute).toHaveAttribute('max', '82')

    await userEvent.clear(minute)
    await userEvent.type(minute, '60')
    await userEvent.click(screen.getByRole('button', { name: 'Go' }))
    expect(onCommand).toHaveBeenCalledWith({ command: 'seek', seek_to: { period: 2, match_clock_s: 3600 } })
  })

  it.each(['', '-5', '83'])('does not seek to minute %j', async (value) => {
    const onCommand = renderControls(viewer())
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Period' }), '2nd half')
    const minute = screen.getByRole('spinbutton', { name: 'Minute' })
    await userEvent.clear(minute)
    if (value) await userEvent.type(minute, value)
    await userEvent.click(screen.getByRole('button', { name: 'Go' }))
    expect(onCommand).not.toHaveBeenCalled()
  })

  it('leaves a finished period open-ended, for its stoppage time', async () => {
    renderControls(viewer())
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Period' }), '1st half')
    expect(screen.getByRole('spinbutton', { name: 'Minute' })).toHaveAttribute('max', '130')
  })

  it('cannot play or pause at the end, but can seek back', () => {
    renderControls(viewer({ state: 'ended' }))
    expect(screen.getByRole('button', { name: 'Play' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Go live' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Go' })).toBeEnabled()
  })

  it.each([
    ['before the status arrives', null],
    ['before a match arrives', status({ state: 'waiting' })],
  ])('is disabled %s', (_, s) => {
    renderControls(s)
    for (const control of controls()) {
      expect(control).toBeDisabled()
    }
  })

  it('is disabled while a command is pending', () => {
    renderControls(viewer(), true)
    for (const control of controls()) {
      expect(control).toBeDisabled()
    }
  })
})
