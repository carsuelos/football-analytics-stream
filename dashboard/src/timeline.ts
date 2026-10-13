/**
 * The charts' time axis: minutes actually played. StatsBomb's match clock runs
 * on across periods (the 2nd half starts at 45:00), but stoppage time overlaps
 * the next period: 45+3' in the 1st half and 48' in the 2nd are both at 48:00.
 * So each period starts on the axis where the previous one ended, and ticks
 * and tooltips are labelled as match minutes ("45+3'").
 */

/** Where each period starts on the match clock, and how long it lasts before stoppage time, in minutes. Period 5 is the shootout. */
const PERIODS: Record<number, { start: number; length: number; name: string }> = {
  1: { start: 0, length: 45, name: '1st half' },
  2: { start: 45, length: 45, name: '2nd half' },
  3: { start: 90, length: 15, name: 'Extra time' },
  4: { start: 105, length: 15, name: 'ET 2nd half' },
  5: { start: 120, length: 0, name: 'Penalties' },
}

const TICK_EVERY = 15

/** The period's name, e.g. "2nd half". */
export const periodName = (period: number) => PERIODS[period].name

/** The match minute of a moment in the match, e.g. "60'", "45+3'" or "Pens". */
export const matchMinute = ({ period, match_clock_s }: Position) => minuteLabel(period, match_clock_s / 60)

function minuteLabel(period: number, clockMinutes: number) {
  if (period === 5) return 'Pens'
  // Without the epsilon, floating-point error can put a tick at 59.999… and label it 59'.
  const minute = Math.floor(clockMinutes + 1e-9)
  const end = PERIODS[period].start + PERIODS[period].length
  return minute > end ? `${end}+${minute - end}'` : `${minute}'`
}

export interface Position {
  /** 1-5, as the schema guarantees. */
  period: number
  match_clock_s: number
}

export interface Timeline {
  /** The axis position of a moment in the match, in minutes played. */
  x(at: Position): number
  /** The match minute at an axis position, e.g. "60'", "45+3'" or "Pens". */
  label(x: number): string
  /** From kick-off to the end of what has been played, or of normal time if that is later. */
  domain: [number, number]
  ticks: number[]
  /** Where each period after the first starts on the axis. */
  periodStarts: { x: number; name: string }[]
}

/**
 * Builds the axis from the positions seen so far. A period lasts as long as
 * its normal length or its latest position, whichever is longer, so the axis
 * stretches as stoppage time is played.
 */
export function timeline(positions: Iterable<Position>): Timeline {
  const played = new Map<number, number>()
  for (const { period, match_clock_s } of positions) {
    const into = match_clock_s / 60 - PERIODS[period].start
    played.set(period, Math.max(played.get(period) ?? 0, into))
  }

  const last = Math.max(2, ...played.keys())
  const offsets = [0, 0]
  for (let p = 1; p <= last; p++) {
    offsets[p + 1] = offsets[p] + Math.max(PERIODS[p].length, played.get(p) ?? 0)
  }

  const x = ({ period, match_clock_s }: Position) => offsets[period] + match_clock_s / 60 - PERIODS[period].start

  const label = (at: number) => {
    let p = 1
    while (p < last && at >= offsets[p + 1]) p++
    return minuteLabel(p, PERIODS[p].start + at - offsets[p])
  }

  const ticks: number[] = []
  const periodStarts: Timeline['periodStarts'] = []
  for (let p = 1; p <= last; p++) {
    const { start, length, name } = PERIODS[p]
    for (let m = start; m < start + length; m += TICK_EVERY) {
      ticks.push(x({ period: p, match_clock_s: m * 60 }))
    }
    if (p > 1) {
      periodStarts.push({ x: offsets[p], name })
    }
  }

  return { x, label, domain: [0, offsets[last + 1]], ticks, periodStarts }
}
