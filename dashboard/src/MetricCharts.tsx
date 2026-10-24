import { useMemo, useState } from 'react'
import { Area, AreaChart, CartesianGrid, Line, LineChart, ReferenceLine, Tooltip, XAxis, YAxis } from 'recharts'
import { chartPoints, type ChartPoint } from './chartData'
import { HeadToHead } from './HeadToHead'
import { DISALLOWED, GOAL, marks, RED_CARD, type Mark } from './chartMarks'
import type { Alert } from './schema/alert.schema'
import type { BroadcastState } from './schema/broadcast_status.schema'
import type { Team } from './schema/engine_status.schema'
import type { Incident } from './schema/incident.schema'
import type { MetricSnapshot, TeamMetrics } from './schema/metric.schema'
import type { Timeline } from './timeline'
import { segmentClass, segmentsClass } from './ui'

const WINDOWS = [
  { window_s: 300, label: "5'" },
  { window_s: 600, label: "10'" },
]

const COLOURS = { home: 'var(--color-home)', away: 'var(--color-away)' }

/** Events and alerts within this many minutes of a hovered point are listed in its tooltip. */
const NEARBY_MIN = 0.5

const percent = (v: number) => `${Math.round(v * 100)}%`

type Metric = Exclude<keyof TeamMetrics, 'team_id'>

interface Props {
  /** Home first, or null until the match's teams are known. */
  teams: Team[] | null
  snapshots: MetricSnapshot[]
  alerts: Alert[]
  incidents?: Incident[]
  axis: Timeline
  /** The simulator's broadcast, to explain why there are no metrics yet. */
  broadcastState?: BroadcastState
  /** Whether there is a simulator to choose a match with; otherwise the feed starts one. */
  simulator?: boolean
}

/**
 * Field tilt, xT added and pressure over the match, for a 5' or 10' window,
 * with the latest values head to head. Goals, red cards and alerts are marked
 * on every chart; hovering shows the values and what happened around then.
 */
export function MetricCharts({ teams, snapshots, alerts, incidents = [], axis, broadcastState, simulator = true }: Props) {
  const [window_s, setWindow] = useState(300)
  const points = useMemo(() => (teams ? chartPoints(snapshots, window_s, teams, axis) : []), [snapshots, window_s, teams, axis])

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {teams && (
          <ul aria-label="Teams" className="flex gap-4 text-sm text-slate-300">
            <li className="flex items-center gap-2">
              <span className="h-1 w-4 rounded-full bg-home" /> {teams[0].name}
            </li>
            <li className="flex items-center gap-2">
              <span className="h-1 w-4 rounded-full bg-away" /> {teams[1].name}
            </li>
          </ul>
        )}
        <div className="ml-auto flex items-center gap-2 text-xs text-slate-400">
          <span>Last</span>
          <div role="group" aria-label="Window" className={segmentsClass}>
            {WINDOWS.map((w) => (
              <button key={w.window_s} type="button" className={segmentClass} aria-pressed={window_s === w.window_s} onClick={() => setWindow(w.window_s)}>
                {w.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      {teams === null || points.length === 0 ? (
        <p className="py-16 text-center text-slate-400">
          {teams === null
            ? simulator
              ? 'No match yet. Choose one in the Simulator panel.'
              : 'No match yet. Waiting for the feed to start one…'
            : simulator && broadcastState === 'paused'
              ? 'The broadcast is paused. Press Play in the Simulator panel to start it.'
              : 'Waiting for the first metrics (one every 5 seconds of play)…'}
        </p>
      ) : (
        <>
          <HeadToHead teams={teams} latest={points[points.length - 1]} />
          <MetricChart title="Field tilt" hint="Share of final-third touches" metric="field_tilt" format={percent} stacked {...{ points, axis, alerts, incidents, teams }} />
          <MetricChart title="xT added" hint="Expected threat from passes and carries" metric="xt_added" format={(v) => v.toFixed(2)} {...{ points, axis, alerts, incidents, teams }} />
          <MetricChart title="Pressure index" hint="Recoveries, box entries, shots and sustained attacks" metric="pressure_index" format={(v) => v.toFixed(1)} {...{ points, axis, alerts, incidents, teams }} />
        </>
      )}
    </div>
  )
}

interface ChartProps {
  title: string
  hint: string
  metric: Metric
  format: (value: number) => string
  /** Draw the teams' shares as stacked areas (they add up to 100%) instead of two lines. */
  stacked?: boolean
  points: ChartPoint[]
  axis: Timeline
  alerts: Alert[]
  incidents: Incident[]
  teams: Team[]
}

function MetricChart({ title, hint, metric, format, stacked, points, axis, alerts, incidents, teams }: ChartProps) {
  const Chart = stacked ? AreaChart : LineChart
  const all = useMemo(() => marks(alerts, incidents, teams, axis), [alerts, incidents, teams, axis])
  const series = (['home', 'away'] as const).map((side, i) => {
    const common = { dataKey: `${side}.${metric}`, name: teams[i].name, stroke: COLOURS[side], isAnimationActive: false }
    return stacked ? (
      <Area key={side} {...common} type="monotone" stackId={metric} fill={`url(#fill-${side})`} strokeWidth={1.5} />
    ) : (
      <Line key={side} {...common} type="monotone" dot={false} strokeWidth={2} />
    )
  })

  return (
    <figure aria-label={title} className="flex flex-col gap-1">
      <figcaption className="flex items-baseline gap-2">
        <span className="text-sm font-semibold text-slate-200">{title}</span>
        <span className="text-xs text-slate-500">{hint}</span>
      </figcaption>
      <Chart responsive data={points} syncId="metrics" style={{ width: '100%', height: 170 }} margin={{ top: 14, right: 10, bottom: 0, left: -12 }}>
        <defs>
          {(['home', 'away'] as const).map((side) => (
            <linearGradient key={side} id={`fill-${side}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={COLOURS[side]} stopOpacity={0.55} />
              <stop offset="100%" stopColor={COLOURS[side]} stopOpacity={0.25} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
        <XAxis type="number" dataKey="x" domain={axis.domain} ticks={axis.ticks} tickFormatter={axis.label} allowDataOverflow stroke="#475569" tickLine={false} axisLine={false} fontSize={11} />
        <YAxis stroke="#475569" tickLine={false} axisLine={false} fontSize={11} tickFormatter={format} {...(stacked ? { domain: [0, 1], ticks: [0, 0.5, 1] } : {})} />
        <Tooltip
          cursor={{ stroke: 'var(--chart-line)', strokeWidth: 1 }}
          content={({ active, payload }) => {
            const point = payload?.[0]?.payload as ChartPoint | undefined
            if (!active || !point) return null
            return <ChartTooltip point={point} metric={metric} format={format} teams={teams} axis={axis} nearby={all.filter((m) => Math.abs(m.x - point.x) <= NEARBY_MIN)} />
          }}
        />
        {axis.periodStarts.map((p) => (
          <ReferenceLine key={p.name} x={p.x} stroke="var(--chart-period)" strokeDasharray="3 4" label={{ value: p.name, position: 'insideTopLeft', fill: '#64748b', fontSize: 10 }} />
        ))}
        {all.map((m) => (
          <ReferenceLine
            key={m.id}
            x={m.x}
            stroke={m.colour}
            strokeOpacity={m.shape === 'alert' ? 0.55 : 0.9}
            strokeWidth={m.shape === 'alert' ? 1 : 1.5}
            strokeDasharray={m.shape === 'alert' ? '2 3' : m.shape === 'disallowed' ? '4 3' : undefined}
            label={<MarkLabel mark={m} />}
          />
        ))}
        {series}
      </Chart>
    </figure>
  )
}

/** The marker at the top of a reference line, with its description on hover. */
function MarkLabel({ mark, viewBox }: { mark: Mark; viewBox?: { x?: number; y?: number } }) {
  const x = viewBox?.x ?? 0
  const y = (viewBox?.y ?? 0) - 6
  return (
    <g className="cursor-help" data-mark={mark.shape}>
      <title>{mark.title}</title>
      {/* A wider invisible target, so the thin line is easy to hover. */}
      <rect x={x - 6} y={y - 6} width={12} height={170} fill="transparent" />
      {mark.shape === 'goal' && <circle cx={x} cy={y} r={5} fill={GOAL} stroke="#0b0f1a" strokeWidth={1.5} />}
      {mark.shape === 'disallowed' && <circle cx={x} cy={y} r={4.5} fill="none" stroke={DISALLOWED} strokeWidth={1.5} />}
      {mark.shape === 'card' && <rect x={x - 3} y={y - 5} width={6} height={9} rx={1} fill={RED_CARD} />}
      {mark.shape === 'alert' && <circle cx={x} cy={y} r={2.5} fill={mark.colour} />}
    </g>
  )
}

function ChartTooltip({ point, metric, format, teams, axis, nearby }: { point: ChartPoint; metric: Metric; format: (v: number) => string; teams: Team[]; axis: Timeline; nearby: Mark[] }) {
  return (
    <div className="max-w-72 rounded-xl border border-white/10 bg-ink-800/95 px-3 py-2 text-xs shadow-2xl backdrop-blur">
      <p className="mb-1 font-semibold text-slate-200">{axis.label(point.x)}</p>
      {(['home', 'away'] as const).map((side, i) => (
        <p key={side} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-slate-300">
            <span className={`h-1 w-3 rounded-full ${side === 'home' ? 'bg-home' : 'bg-away'}`} /> {teams[i].name}
          </span>
          <span className="font-mono font-semibold tabular-nums">{format(point[side][metric])}</span>
        </p>
      ))}
      {nearby.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1 border-t border-white/10 pt-2">
          {nearby.map((m) => (
            <li key={m.id} className="flex gap-1.5 text-slate-300">
              <span className="mt-1 size-1.5 shrink-0 rounded-full" style={{ background: m.colour }} />
              {m.title}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
