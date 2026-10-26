import { useEffect, useState, type ReactNode } from 'react'

/**
 * The match feed as a panel sliding in from the right, over everything: for
 * when the window is too narrow for the feed beside the charts (it moves to
 * the bottom), e.g. tiled next to a match video. The button shows only then.
 */
export function FeedDrawer({ count, children }: { count: number; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])
  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        aria-controls="feed-drawer"
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-xs font-semibold text-slate-300 transition hover:text-slate-100 lg:hidden"
      >
        <svg viewBox="0 0 24 24" className="size-3.5" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M4 6h16M4 12h16M4 18h10" />
        </svg>
        Match feed{' '}
        {count > 0 && <span className="rounded-full bg-sky-400/20 px-1.5 text-[10px] text-sky-200 tabular-nums">{count}</span>}
      </button>
      {open && (
        <div className="fixed inset-0 z-50 lg:hidden" onClick={() => setOpen(false)}>
          <div className="absolute inset-0 bg-black/50 backdrop-blur-[2px]" />
          <aside
            id="feed-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Match feed panel"
            onClick={(e) => e.stopPropagation()}
            className="absolute inset-y-0 right-0 flex w-[min(26rem,92vw)] animate-[toast-in_0.2s_ease-out] flex-col border-l border-white/10 bg-ink-900 p-4 shadow-2xl"
          >
            <div className="mb-2 flex justify-end">
              <button type="button" aria-label="Close" onClick={() => setOpen(false)} className="rounded-md px-2 text-xl text-slate-400 hover:bg-white/10 hover:text-slate-100">
                ×
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
          </aside>
        </div>
      )}
    </>
  )
}
