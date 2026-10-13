import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatusBar } from './StatusBar'
import { status } from './test/factories'

describe('StatusBar', () => {
  it('shows the connection before the engine has said anything', () => {
    const { container } = render(<StatusBar connection="connecting" status={null} />)
    expect(screen.getByRole('status')).toHaveTextContent(/^Connecting…$/)
    expect(container).toHaveTextContent(/^Connecting…$/)
  })

  it("shows the engine's state and the match clock", () => {
    const { container } = render(<StatusBar connection="open" status={status({ state: 'live', period: 2, match_clock_s: 91 * 60 })} />)
    expect(screen.getByRole('status')).toHaveTextContent('Connected Live')
    expect(container).toHaveTextContent("Match clock: 90+1' · 2nd half")
  })

  it('names the shootout without a minute', () => {
    const { container } = render(<StatusBar connection="open" status={status({ state: 'ended', period: 5, match_clock_s: 7559 })} />)
    expect(container).toHaveTextContent(/Ended\s*Match clock: Penalties$/)
  })

  it('keeps the last state on screen, dimmed, while reconnecting', () => {
    render(<StatusBar connection="lost" status={status({ state: 'rebuilding' })} />)
    expect(screen.getByRole('status')).toHaveTextContent('Reconnecting… Catching up')
    expect(screen.getByText('Catching up')).toHaveClass('opacity-50')
    expect(screen.getByText("10'", { exact: false })).toHaveClass('opacity-50')
  })

  it('leaves out the clock until an event has been processed', () => {
    const { container } = render(<StatusBar connection="open" status={status({ state: 'waiting', period: undefined, match_clock_s: undefined })} />)
    expect(container).toHaveTextContent(/^Connected\s*Waiting for a match$/)
  })
})
