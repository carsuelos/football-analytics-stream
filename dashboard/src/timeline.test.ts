import { describe, expect, it } from 'vitest'
import { matchMinute, periodName, timeline } from './timeline'

const at = (period: number, minute: number) => ({ period, match_clock_s: minute * 60 })

describe('timeline', () => {
  it('spans normal time before anything has been played', () => {
    const axis = timeline([])
    expect(axis.domain).toEqual([0, 90])
    expect(axis.ticks).toEqual([0, 15, 30, 45, 60, 75])
    expect(axis.periodStarts).toEqual([{ x: 45, name: '2nd half' }])
    expect(axis.x(at(1, 30))).toBe(30)
    expect(axis.x(at(2, 60))).toBe(60)
  })

  it('starts the 2nd half where 1st-half stoppage time ended', () => {
    const axis = timeline([at(1, 30), at(1, 48), at(2, 50)])
    expect(axis.x(at(1, 48))).toBe(48)
    expect(axis.x(at(2, 45))).toBe(48)
    expect(axis.x(at(2, 50))).toBe(53)
    expect(axis.domain).toEqual([0, 93])
    expect(axis.ticks).toEqual([0, 15, 30, 48, 63, 78])
    expect(axis.periodStarts).toEqual([{ x: 48, name: '2nd half' }])
  })

  it('takes the latest position in each period, in any order', () => {
    // Alerts come after the snapshots, but can be from earlier in the match.
    expect(timeline([at(1, 48), at(1, 30)]).x(at(2, 45))).toBe(48)
  })

  it('labels the ticks with whole minutes, despite floating-point error', () => {
    const axis = timeline([{ period: 1, match_clock_s: 2704 }])
    expect(axis.ticks.map(axis.label)).toEqual(["0'", "15'", "30'", "45'", "60'", "75'"])
  })

  it('labels axis positions as match minutes, with stoppage time', () => {
    const axis = timeline([at(1, 48), at(2, 94.5)])
    expect(axis.label(0)).toBe("0'")
    expect(axis.label(44.5)).toBe("44'")
    expect(axis.label(45)).toBe("45'")
    expect(axis.label(47.5)).toBe("45+2'")
    expect(axis.label(48)).toBe("45'")
    expect(axis.label(63)).toBe("60'")
    expect(axis.label(48 + 49.5)).toBe("90+4'")
    expect(axis.domain).toEqual([0, 97.5])
  })

  it('adds extra time and the shootout once they are played', () => {
    const axis = timeline([at(1, 47), at(2, 98), at(3, 106), at(4, 123), at(5, 126)])
    // 1st half 47', 2nd 53', ET 16', ET 2nd 18', shootout 6'.
    expect(axis.periodStarts).toEqual([
      { x: 47, name: '2nd half' },
      { x: 100, name: 'Extra time' },
      { x: 116, name: 'ET 2nd half' },
      { x: 134, name: 'Penalties' },
    ])
    expect(axis.domain).toEqual([0, 140])
    expect(axis.ticks).toEqual([0, 15, 30, 47, 62, 77, 100, 116])
    expect(axis.label(99)).toBe("90+7'")
    expect(axis.label(120)).toBe("109'")
    expect(axis.label(135)).toBe('Pens')
  })

  it('labels a moment as its match minute and period', () => {
    expect(matchMinute(at(1, 12.5))).toBe("12'")
    expect(matchMinute(at(1, 47.2))).toBe("45+2'")
    expect(matchMinute(at(2, 45))).toBe("45'")
    expect(matchMinute(at(2, 91))).toBe("90+1'")
    expect(matchMinute(at(4, 121))).toBe("120+1'")
    expect(matchMinute(at(5, 125))).toBe('Pens')
    expect(periodName(3)).toBe('Extra time')
  })
})
