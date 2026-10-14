import type { ChartPoint } from './chartData'
import type { Team } from './schema/engine_status.schema'

const ROWS = [
  { metric: 'field_tilt', label: 'Field tilt', format: (v: number) => `${Math.round(v * 100)}%` },
  { metric: 'xt_added', label: 'xT added', format: (v: number) => v.toFixed(2) },
  { metric: 'pressure_index', label: 'Pressure', format: (v: number) => v.toFixed(1) },
] as const

/** The latest values over the window, each as a bar split between the teams. */
export function HeadToHead({ teams, latest }: { teams: Team[]; latest: ChartPoint }) {
  return (
    <dl aria-label="Head to head" className="grid gap-3 sm:grid-cols-3">
      {ROWS.map(({ metric, label, format }) => {
        const h = Math.max(latest.home[metric], 0)
        const a = Math.max(latest.away[metric], 0)
        const share = h + a > 0 ? h / (h + a) : 0.5
        return (
          <div key={metric} className="rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2.5">
            <dt className="eyebrow mb-1.5 text-center">{label}</dt>
            <dd className="flex items-center justify-between font-mono text-sm font-semibold tabular-nums">
              <span className="text-home">
                <span className="sr-only">{teams[0].name} </span>
                {format(latest.home[metric])}
              </span>
              <span className="text-away">
                <span className="sr-only">{teams[1].name} </span>
                {format(latest.away[metric])}
              </span>
            </dd>
            <dd aria-hidden="true" className="mt-1.5 flex h-1.5 overflow-hidden rounded-full bg-white/5">
              <span className="bg-home transition-[width] duration-500" style={{ width: `${share * 100}%` }} />
              <span className="flex-1 bg-away" />
            </dd>
          </div>
        )
      })}
    </dl>
  )
}
