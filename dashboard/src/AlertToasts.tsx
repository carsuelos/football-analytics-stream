import { useEffect } from 'react'
import { AlertIcon } from './Icons'
import { TOAST_MS, type Toast } from './notifications'
import type { Team } from './schema/engine_status.schema'

/**
 * New alerts popping up at the top right, under the header: each stays
 * TOAST_MS unless closed. The newest is at the bottom of the stack.
 */
export function AlertToasts({ toasts, teams, onDismiss }: { toasts: Toast[]; teams: Team[] | null; onDismiss: (id: string) => void }) {
  return (
    <ol aria-label="New alerts" aria-live="polite" className="pointer-events-none fixed top-20 right-4 z-40 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2">
      {toasts.map((t) => (
        <ToastCard key={t.id} toast={t} home={teams?.[0]?.id} onDismiss={onDismiss} />
      ))}
    </ol>
  )
}

function ToastCard({ toast: t, home, onDismiss }: { toast: Toast; home?: number; onDismiss: (id: string) => void }) {
  useEffect(() => {
    const timer = setTimeout(() => onDismiss(t.id), TOAST_MS)
    return () => clearTimeout(timer)
  }, [t.id, onDismiss])
  const side = home === undefined ? 'border-l-slate-500' : t.alert.team_id === home ? 'border-l-home' : 'border-l-away'
  return (
    <li
      className={`pointer-events-auto flex animate-[toast-in_0.25s_ease-out] items-start gap-3 rounded-xl border border-white/10 border-l-[3px] ${side} bg-ink-800/95 px-3.5 py-3 shadow-2xl shadow-black/40 backdrop-blur`}
    >
      <AlertIcon type={t.alert.type} className="mt-0.5 size-4 shrink-0 text-sky-300" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-slate-100">{t.title}</p>
        <p className="mt-0.5 text-xs text-slate-300">{t.body}</p>
      </div>
      <button type="button" aria-label="Close" onClick={() => onDismiss(t.id)} className="-mt-0.5 -mr-1 rounded-md px-1.5 text-slate-500 hover:bg-white/10 hover:text-slate-200">
        ×
      </button>
    </li>
  )
}
