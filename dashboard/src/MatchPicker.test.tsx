import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MatchPicker } from './MatchPicker'
import { matchInfo } from './test/factories'

const MATCHES = [matchInfo(3869685), matchInfo(3857256, { id: 768, name: 'England' }, { id: 771, name: 'France' })]

describe('MatchPicker', () => {
  it('lists the matches without their scores', () => {
    render(<MatchPicker matches={MATCHES} disabled={false} onLoad={vi.fn()} />)
    const options = screen.getAllByRole('option').map((o) => o.textContent)
    expect(options).toEqual([
      'Choose a match…',
      'Argentina v France · FIFA World Cup Final · 2022-12-18',
      'England v France · FIFA World Cup Final · 2022-12-18',
    ])
    expect(screen.getByRole('combobox', { name: 'Match' })).toHaveValue('')
  })

  it('loads the chosen match', async () => {
    const onLoad = vi.fn()
    render(<MatchPicker matches={MATCHES} disabled={false} onLoad={onLoad} />)
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Match' }), 'England v France · FIFA World Cup Final · 2022-12-18')
    expect(onLoad).toHaveBeenCalledWith(3857256)
  })

  it('shows the loaded match, even if it was loaded elsewhere', () => {
    const { rerender } = render(<MatchPicker matches={MATCHES} matchId={3869685} disabled={false} onLoad={vi.fn()} />)
    expect(screen.getByRole('combobox', { name: 'Match' })).toHaveValue('3869685')

    rerender(<MatchPicker matches={MATCHES} matchId={3857256} disabled={false} onLoad={vi.fn()} />)
    expect(screen.getByRole('combobox', { name: 'Match' })).toHaveValue('3857256')
  })

  it('is disabled until the matches arrive, and while a command is pending', () => {
    const { rerender } = render(<MatchPicker matches={null} disabled={false} onLoad={vi.fn()} />)
    expect(screen.getByRole('combobox', { name: 'Match' })).toBeDisabled()
    expect(screen.getByRole('option')).toHaveTextContent('Loading matches…')

    rerender(<MatchPicker matches={MATCHES} disabled onLoad={vi.fn()} />)
    expect(screen.getByRole('combobox', { name: 'Match' })).toBeDisabled()
  })
})
