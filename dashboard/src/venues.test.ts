import { describe, expect, it } from 'vitest'
import { ago, cents, percent } from './venues'

describe('venues', () => {
  it('writes prices in cents, to a tenth where needed', () => {
    expect(cents(0.52)).toBe('52¢')
    expect(cents(0.535)).toBe('53.5¢')
    expect(cents(0.79995)).toBe('80¢')
    expect(cents(0.0107)).toBe('1.1¢')
  })

  it('writes probabilities and ages', () => {
    expect(percent(0.535)).toBe('54%')
    const now = Date.parse('2026-10-24T18:00:00Z')
    expect(ago('2026-10-24T18:00:00Z', now)).toBe('just now')
    expect(ago('2026-10-24T17:59:20Z', now)).toBe('40s ago')
    expect(ago('2026-10-24T17:57:00Z', now)).toBe('3m ago')
  })
})
