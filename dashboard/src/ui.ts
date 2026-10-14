/** A toggle or action button; aria-pressed marks the selected toggle. */
export const buttonClass =
  'inline-flex items-center justify-center gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.04] px-3 py-1.5 text-sm font-medium text-slate-200 transition hover:bg-white/[0.09] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-white/[0.04] aria-pressed:border-sky-400/40 aria-pressed:bg-sky-400/15 aria-pressed:text-sky-200'

/** A segment in a group of toggles that sit together. */
export const segmentClass =
  'rounded-md px-2.5 py-1 text-xs font-semibold text-slate-400 transition hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-40 aria-pressed:bg-white/10 aria-pressed:text-white aria-pressed:shadow-sm'

/** The container of a group of segments. */
export const segmentsClass = 'flex items-center gap-0.5 rounded-lg border border-white/[0.06] bg-black/20 p-0.5'

export const selectClass =
  'rounded-lg border border-white/[0.08] bg-ink-800 px-3 py-1.5 text-sm text-slate-100 transition hover:border-white/15 disabled:opacity-40'
