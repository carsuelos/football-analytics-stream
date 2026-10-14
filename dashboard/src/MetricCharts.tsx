import { useMemo, useState } from 'react'
import { Area, AreaChart, CartesianGrid, Line, LineChart, ReferenceLine, Tooltip, XAxis, YAxis } from 'recharts'
import { chartPoints, type ChartPoint } from './chartData'
import type { Alert } from './schema/alert.schema'
import type { BroadcastState } from './schema/broadcast_status.schema'
import type { Team } from './schema/engine_status.schema'
import type { MetricSnapshot, TeamMetrics } from './schema/metric.schema'
import { timeline, type Timeline } from './timeline'
import { buttonClass } from './ui'

const WINDOWS = [
  { window_s: 300, label: "5'" },
  { window_s: 600, label: "10'" },
]

const COLOURS = { home: 'var(--color-home)', away: 'var(--color-away)' }

const percent = (v: number) => `${Math.round(v * 100)}%`

interface Props {
  /** Home first, or null until the match's teams are known. */
  teams: Team[] | null
  snapshots: MetricSnapshot[]
  alerts: Alert[]
  /** The simulator's broadcast, to explain why there are no metrics yet. */
  broadcastState?: BroadcastState
  /** Whether there is a simulator to choose a match with; otherwise the feed starts one. */
  simulator?: boolean
}

/** Field tilt, xT added and pressure over the match, for a 5' or 10' window, with alerts marked. */
export function MetricCharts({ teams, snapshots, alerts, broadcastState, simulator = true }: Props) {
  const [window_s, setWindow] = useState(300)
  const axis = useMemo(() => timeline([...snapshots, ...alerts]), [snapshots, alerts])
  const points = useMemo(
    () => (teams ? chartPoints(snapshots, window_s, teams, axis) : []),
    [snapshots, window_s, teams, axis],
  )

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {teams && (
          <ul aria-label="Teams" className="flex gap-4 text-sm">
            <li className="flex items-center gap-2">
              <span className="size-3 rounded-sm bg-home" /> {teams[0].name}
            </li>
            <li className="flex items-center gap-2">
              <span className="size-3 rounded-sm bg-away" /> {teams[1].name}
            </li>
          </ul>
        )}
        <div role="group" aria-label="Window" className="ml-auto flex items-center gap-1 text-sm">
          <span className="mr-1 text-slate-400">Window</span>
          {WINDOWS.map((w) => (
            <button
              key={w.window_s}
              type="button"
              className={buttonClass}
              aria-pressed={window_s === w.window_s}
              onClick={() => setWindow(w.window_s)}
            >
              {w.label}
            </button>
          ))}
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
          <MetricChart title="Field tilt" metric="field_tilt" format={percent} stacked {...{ points, axis, alerts, teams }} />
          <MetricChart title="xT added" metric="xt_added" format={(v) => v.toFixed(2)} {...{ points, axis, alerts, teams }} />
          <MetricChart title="Pressure index" metric="pressure_index" format={(v) => v.toFixed(1)} {...{ points, axis, alerts, teams }} />
        </>
      )}
    </div>
  )
}

interface ChartProps {
  title: string
  metric: Exclude<keyof TeamMetrics, 'team_id'>
  format: (value: number) => string
  /** Draw the teams' shares as stacked areas (they add up to 100%) instead of two lines. */
  stacked?: boolean
  points: ChartPoint[]
  axis: Timeline
  alerts: Alert[]
  teams: Team[]
}

function MetricChart({ title, metric, format, stacked, points, axis, alerts, teams }: ChartProps) {
  const Chart = stacked ? AreaChart : LineChart
  const series = (['home', 'away'] as const).map((side, i) => {
    const common = {
      dataKey: `${side}.${metric}`,
      name: teams[i].name,
      stroke: COLOURS[side],
      isAnimationActive: false,
    }
    return stacked ? (
      <Area key={side} {...common} type="monotone" stackId={metric} fill={COLOURS[side]} fillOpacity={0.6} />
    ) : (
      <Line key={side} {...common} type="monotone" dot={false} strokeWidth={2} />
    )
  })

  return (
    <figure aria-label={title} className="flex flex-col gap-1">
      <figcaption className="text-sm font-medium text-slate-300">{title}</figcaption>
      <Chart responsive data={points} syncId="metrics" style={{ width: '100%', height: 180 }} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
        <CartesianGrid stroke="#1e293b" vertical={false} />
        <XAxis
          type="number"
          dataKey="x"
          domain={axis.domain}
          ticks={axis.ticks}
          tickFormatter={axis.label}
          allowDataOverflow
          stroke="#64748b"
          fontSize={12}
        />
        <YAxis
          stroke="#64748b"
          fontSize={12}
          tickFormatter={format}
          {...(stacked ? { domain: [0, 1], ticks: [0, 0.5, 1] } : {})}
        />
        <Tooltip
          labelFormatter={(x) => axis.label(Number(x))}
          formatter={(value) => format(Number(value))}
          contentStyle={{ background: '#0f172a', border: '1px solid #334155' }}
        />
        {axis.periodStarts.map((p) => (
          <ReferenceLine key={p.name} x={p.x} stroke="#64748b" strokeDasharray="4 4" label={{ value: p.name, position: 'insideTopLeft', fill: '#94a3b8', fontSize: 11 }} />
        ))}
        {alerts.map((a) => (
          <ReferenceLine key={a.id} x={axis.x(a)} stroke={a.team_id === teams[0].id ? COLOURS.home : COLOURS.away} strokeWidth={1.5} />
        ))}
        {series}
      </Chart>
    </figure>
  )
}
