import type { CSSProperties } from 'react'

/**
 * Each team's colours, in its kit's order: first the colour it's known by,
 * then alternates for when it clashes with the opponent's. White and black
 * are skipped when picking (they can't be read on both themes), so a white
 * kit lists its accent next. Names as the data gives them, without "Women's".
 * Teams not listed keep the dashboard's blue (home) and orange (away).
 */
const KITS: Record<string, string[]> = {
  // National teams
  Argentina: ['#6cace4', '#ffffff'],
  Australia: ['#ffcd00', '#00843d'],
  Belgium: ['#e30613', '#000000'],
  Brazil: ['#ffdf00', '#009c3b'],
  Cameroon: ['#007a5e', '#ce1126'],
  Canada: ['#d52b1e', '#ffffff'],
  'Costa Rica': ['#ce1126', '#002b7f'],
  Croatia: ['#ff0000', '#171796'],
  Denmark: ['#c8102e', '#ffffff'],
  Ecuador: ['#ffd100', '#034ea2'],
  England: ['#ffffff', '#cf142b', '#00247d'],
  Finland: ['#ffffff', '#002f6c'],
  France: ['#002395', '#ed2939'],
  Germany: ['#ffffff', '#000000', '#ffce00', '#dd0000'],
  Ghana: ['#ffffff', '#ce1126', '#fcd116'],
  Iceland: ['#02529c', '#dc1e35'],
  Iran: ['#ffffff', '#da0000', '#239f40'],
  Italy: ['#0066b3', '#ffffff'],
  Japan: ['#0b2fa8', '#ffffff'],
  Mexico: ['#006847', '#ce1126'],
  Morocco: ['#c1272d', '#006233'],
  Netherlands: ['#ff6600', '#21468b'],
  Norway: ['#ba0c2f', '#00205b'],
  Poland: ['#ffffff', '#dc143c'],
  Portugal: ['#c8102e', '#046a38'],
  Qatar: ['#8a1538', '#ffffff'],
  'Saudi Arabia': ['#006c35', '#ffffff'],
  Senegal: ['#ffffff', '#00853f', '#fdef42'],
  Serbia: ['#c6363c', '#0c4076'],
  'South Korea': ['#c60c30', '#003478'],
  Spain: ['#c60b1e', '#ffc400'],
  Sweden: ['#fecc02', '#006aa7'],
  Switzerland: ['#d52b1e', '#ffffff'],
  Tunisia: ['#e70013', '#ffffff'],
  'United States': ['#ffffff', '#002868', '#bf0a30'],
  Uruguay: ['#5cbfeb', '#000000'],
  Wales: ['#c8102e', '#00b140'],
  // Clubs
  Arsenal: ['#ef0107', '#063672'],
  Barcelona: ['#a50044', '#004d98'],
  'Bayern Munich': ['#dc052d', '#0066b2'],
  Chelsea: ['#034694', '#ffffff'],
  'Borussia Dortmund': ['#fde100', '#000000'],
  Liverpool: ['#c8102e', '#00b2a9'],
  'Manchester City': ['#6cabdd', '#1c2c5b'],
  'Manchester United': ['#da291c', '#fbe122'],
  'Real Madrid': ['#ffffff', '#febe10', '#00529f'],
  Tottenham: ['#ffffff', '#132257'],
}

/** How a team's name in the data reads in KITS: "Norway Women's", "Wales W" and "WNT Finland" are their countries. */
export function kitName(name: string): string {
  return name
    .replace(/\s+Women's$/i, '')
    .replace(/\s+W$/, '')
    .replace(/^WNT\s+/, '')
    .replace(/\s+FC$/, '')
    .trim()
}

interface Lch {
  l: number
  c: number
  h: number
}

/** A #rrggbb colour in OKLCH (Björn Ottosson's OKLab, in polar form). */
export function oklch(hex: string): Lch {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const v = parseInt(hex.slice(i, i + 2), 16) / 255
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  })
  const l_ = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m_ = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s_ = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  const L = 0.2104542553 * l_ + 0.793617785 * m_ - 0.0040720468 * s_
  const A = 1.9779984951 * l_ - 2.428592205 * m_ + 0.4505937099 * s_
  const B = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.808675766 * s_
  return { l: L, c: Math.hypot(A, B), h: ((Math.atan2(B, A) * 180) / Math.PI + 360) % 360 }
}

/** Below this chroma a colour is white, black or grey: not a team's colour on screen. */
const GREY = 0.04
/** Lightness kept within this range, so a colour reads on both the dark and the light theme. */
const LIGHTNESS: [number, number] = [0.56, 0.76]
/** Two colours whose hues are closer than this would be hard to tell apart in the charts. */
const MIN_HUE_GAP = 40

const hueGap = (a: Lch, b: Lch) => {
  const d = Math.abs(a.h - b.h) % 360
  return Math.min(d, 360 - d)
}

const readable = (c: Lch): Lch => ({ ...c, l: Math.min(Math.max(c.l, LIGHTNESS[0]), LIGHTNESS[1]) })

/** A team's usable colours, in order: its kit's, without white and black, adjusted to read on screen. */
function colours(name: string): Lch[] {
  return (KITS[kitName(name)] ?? []).map(oklch).filter((c) => c.c >= GREY).map(readable)
}

const css = (c: Lch) => `oklch(${c.l.toFixed(3)} ${c.c.toFixed(3)} ${c.h.toFixed(1)})`

/**
 * The home and away colours for a match: each team's first colour, the away
 * team's (or then the home team's) next one if they clash, and the
 * dashboard's own blue and orange for a team without one.
 */
export function matchColours(home: string, away: string): { home?: string; away?: string } {
  const h = colours(home)
  const a = colours(away)
  for (const [hi, ai] of [
    [0, 0],
    [0, 1],
    [1, 0],
    [0, 2],
    [1, 1],
  ]) {
    const hc = h[hi]
    const ac = a[ai]
    if (hc && ac && hueGap(hc, ac) >= MIN_HUE_GAP) return { home: css(hc), away: css(ac) }
  }
  // Only one team known, or they clash every way: color the known one, if it isn't too close to the default other.
  const DEFAULT_HOME = oklch('#3fb0f0')
  const DEFAULT_AWAY = oklch('#f5a142')
  if (h[0] && hueGap(h[0], DEFAULT_AWAY) >= MIN_HUE_GAP && !a[0]) return { home: css(h[0]) }
  if (a[0] && hueGap(a[0], DEFAULT_HOME) >= MIN_HUE_GAP && !h[0]) return { away: css(a[0]) }
  return {}
}

/** The CSS variables that recolour everything team-coloured (bg-home, the charts...) for a match. */
export function teamColourStyle(teams: { name: string }[] | null): CSSProperties | undefined {
  if (!teams || teams.length < 2) return undefined
  const { home, away } = matchColours(teams[0].name, teams[1].name)
  const style: Record<string, string> = {}
  if (home) style['--color-home'] = home
  if (away) style['--color-away'] = away
  return style as CSSProperties
}
