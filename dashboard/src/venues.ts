import type { Venue } from './schema/market_board.schema'

export const VENUE_ORDER: Venue[] = ['kalshi', 'polymarket', 'novig']

export const VENUES: Record<Venue, { name: string; letter: string; text: string; dot: string; fee: string }> = {
  kalshi: { name: 'Kalshi', letter: 'K', text: 'text-emerald-300', dot: 'bg-emerald-400', fee: '0.07 · p(1−p)' },
  polymarket: { name: 'Polymarket', letter: 'P', text: 'text-sky-300', dot: 'bg-sky-400', fee: '0.0695 · p(1−p)' },
  novig: { name: 'Novig', letter: 'N', text: 'text-violet-300', dot: 'bg-violet-400', fee: '0.06 · p(1−p), in-game only' },
}

/** A price in cents, to a tenth where it has one: 52¢, 53.5¢. */
export function cents(p: number) {
  const c = Math.round(p * 1000) / 10
  return `${Number.isInteger(c) ? c.toFixed(0) : c.toFixed(1)}¢`
}

/** A probability as a whole percent: 54%. */
export const percent = (p: number) => `${Math.round(p * 100)}%`

/** How long ago, roughly: "just now", "40s ago", "3m ago". */
export function ago(iso: string, now: number) {
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000))
  if (s < 5) return 'just now'
  if (s < 60) return `${s}s ago`
  return `${Math.round(s / 60)}m ago`
}
