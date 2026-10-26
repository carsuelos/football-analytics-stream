import { describe, expect, it } from 'vitest'
import { kitName, matchColours, oklch, teamColourStyle } from './teamColours'

const hue = (css?: string) => Number(css?.match(/oklch\([\d.]+ [\d.]+ ([\d.]+)\)/)?.[1])

describe('team colours', () => {
  it('reads the data names', () => {
    expect(["Norway Women's", 'Wales W', 'WNT Finland', 'Argentina'].map(kitName)).toEqual(['Norway', 'Wales', 'Finland', 'Argentina'])
  })

  it('converts to OKLCH', () => {
    const white = oklch('#ffffff')
    expect(white.l).toBeCloseTo(1, 3)
    expect(white.c).toBeCloseTo(0, 3)
    const orange = oklch('#ff6600')
    expect(orange.h).toBeGreaterThan(40)
    expect(orange.h).toBeLessThan(60)
  })

  it("gives each team its colour: Norway's red, Iceland's blue", () => {
    const { home, away } = matchColours("Norway Women's", "Iceland Women's")
    expect(hue(home)).toBeLessThan(35) // red
    expect(hue(away)).toBeGreaterThan(240) // blue
    expect(hue(away)).toBeLessThan(275)
  })

  it('skips white kits for their accent, and keeps the lightness readable', () => {
    const { home } = matchColours('England', 'Netherlands')
    expect(hue(home)).toBeLessThan(35) // England's red, not white
    const l = Number(home?.match(/oklch\(([\d.]+)/)?.[1])
    expect(l).toBeGreaterThanOrEqual(0.56)
    expect(l).toBeLessThanOrEqual(0.76)
  })

  it('switches the away team to its next colour when the two clash', () => {
    const { home, away } = matchColours('Spain', 'Portugal') // both red
    expect(hue(home)).toBeLessThan(35)
    expect(hue(away)).toBeGreaterThan(130) // Portugal's green
  })

  it('keeps the defaults for teams it does not know', () => {
    expect(matchColours('Atlantis', 'Lemuria')).toEqual({})
    expect(teamColourStyle(null)).toBeUndefined()
    expect(teamColourStyle([{ name: 'Norway' }, { name: 'Iceland' }])).toHaveProperty('--color-home')
  })
})
