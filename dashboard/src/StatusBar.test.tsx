import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatusBar } from './StatusBar'
import { status } from './test/factories'

describe('StatusBar', () => {
  it('shows the connection before the engine has said anything', () => {
    render(<StatusBar connection="connecting" status={null} />)
    expect(screen.getByRole('status')).toHaveTextContent(/^Connecting…$/)
  })

  it("shows the engine's state", () => {
    render(<StatusBar connection="open" status={status({ state: 'live' })} />)
    expect(screen.getByRole('status')).toHaveTextContent('Connected Live')
  })

  it('keeps the last state on screen, dimmed, while reconnecting', () => {
    render(<StatusBar connection="lost" status={status({ state: 'rebuilding' })} />)
    expect(screen.getByRole('status')).toHaveTextContent('Reconnecting… Catching up')
    expect(screen.getByText('Catching up')).toHaveClass('opacity-50')
  })
})
