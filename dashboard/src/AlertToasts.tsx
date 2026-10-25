import { useEffect } from 'react'
import { isModelAlert } from './alerts'
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
  const model = isModelAlert(t.alert.type)
  return (
    <li
      className={`pointer-events-auto flex items-start gap-3 rounded-xl border border-l-[3px] ${side} px-3.5 py-3 backdrop-blur ${
        model
          ? 'animate-[toast-in_0.25s_ease-out,model-glow_1.6s_ease-out_2] border-violet-400/50 bg-gradient-to-br from-violet-950/95 via-ink-800/95 to-ink-800/95 shadow-2xl shadow-violet-500/30'
          : 'animate-[toast-in_0.25s_ease-out] border-white/10 bg-ink-800/95 shadow-2xl shadow-black/40'
      }`}
    >
      <AlertIcon type={t.alert.type} className={`mt-0.5 size-4 shrink-0 ${model ? 'text-violet-300' : 'text-sky-300'}`} />
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2 text-sm font-semibold text-slate-100">
          {t.title}
          {model && <span className="rounded-full bg-violet-400/20 px-1.5 py-px text-[10px] font-bold tracking-wider text-violet-200 uppercase">Model</span>}
        </p>
        <p className="mt-0.5 text-xs text-slate-300">{t.body}</p>
      </div>
      <button type="button" aria-label="Close" onClick={() => onDismiss(t.id)} className="-mt-0.5 -mr-1 rounded-md px-1.5 text-slate-500 hover:bg-white/10 hover:text-slate-200">
        ×
      </button>
    </li>
  )
}
