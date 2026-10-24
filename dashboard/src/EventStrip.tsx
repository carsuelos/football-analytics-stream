import { useId, type ReactNode } from 'react'
import { AlertIcon, ChevronIcon, IncidentIcon } from './Icons'
import { cancelledGoals, describe, INCIDENTS, isGoal, scoreline } from './incidents'
import { ALERT_NAMES } from './alerts'
import { LANES, lanes } from './lanes'
import type { Alert } from './schema/alert.schema'
import type { Team } from './schema/engine_status.schema'
import type { Incident } from './schema/incident.schema'
import { matchClock, type Timeline } from './timeline'
import { useStoredFlag } from './useStoredFlag'

interface Props {
  teams: Team[]
  incidents: Incident[]
  alerts: Alert[]
  axis: Timeline
  /** Where the viewer is on the axis. */
  now?: number
}

/**
 * The whole match on one line: events above it, alerts below, home's on the
 * left of each marker's colour key. Hover or focus a marker to see what it is.
 * It starts compact, one row of small markers; a click expands it so markers
 * close together stack instead of overlapping. The choice is remembered.
 */
export function EventStrip({ teams, incidents, alerts, axis, now }: Props) {
  const [expanded, setExpanded] = useStoredFlag('timeline.expanded', false)
  const strip = useId()
  const L = expanded ? FULL : COMPACT
  const [start, end] = axis.domain
  const fraction = (x: number) => (x - start) / (end - start)
  const left = (x: number) => `${fraction(x) * 100}%`
  const cancelled = cancelledGoals(incidents)
  // The shootout has no place on the timeline of play.
  const events = incidents.filter((i) => i.period !== 5)
  const colour = (team_id: number) => (team_id === teams[0].id ? 'bg-home' : 'bg-away')
  const eventLanes = lanes(events.map((i) => fraction(axis.x(i))), EVENT_GAP, L.lanes)
  const alertLanes = lanes(alerts.map((a) => fraction(axis.x(a))), ALERT_GAP, L.lanes)

  return (
    <figure aria-label="Match timeline" className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <figcaption className="eyebrow">Match timeline</figcaption>
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={strip}
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold text-slate-400 transition hover:bg-white/[0.05] hover:text-slate-200"
        >
          {expanded ? 'Compact' : 'Expand'}
          <ChevronIcon className={`size-3 transition-transform ${expanded ? 'rotate-180' : ''}`} />
        </button>
      </div>
      {/* Compact, a click anywhere on it expands it (the markers still show what they are on hover). */}
      <div
        id={strip}
        className={`relative transition-[height] duration-200 ${expanded ? '' : 'cursor-zoom-in'}`}
        style={{ height: L.height }}
        onClick={expanded ? undefined : () => setExpanded(true)}
      >
        <div className="absolute inset-x-0 h-px bg-white/10" style={{ top: L.midline }} />
        {now !== undefined && (
          <div className="absolute left-0 h-0.5 rounded-full bg-gradient-to-r from-sky-400/0 to-sky-400/80" style={{ top: L.midline - 0.5, width: left(Math.min(now, end)) }} />
        )}
        {axis.periodStarts.map((p) => (
          <div key={p.name} className="absolute w-px bg-white/10" style={{ left: left(p.x), top: L.midline - L.periodTick, height: 2 * L.periodTick }} />
        ))}
        {axis.ticks.map((t) => (
          <span key={t} className="absolute bottom-0 -translate-x-1/2 text-[10px] text-slate-500 tabular-nums" style={{ left: left(t) }}>
            {axis.label(t)}
          </span>
        ))}
        <ul aria-label="Events">
          {events.map((i, n) => (
            <Marker
              key={i.id}
              left={left(axis.x(i))}
              align={align(fraction(axis.x(i)))}
              top={L.eventTop(eventLanes[n])}
              above
              label={`${matchClock(i)} · ${describe(i)}${cancelled.has(i.id) ? ' (disallowed)' : ''}${isGoal(i) ? ` · ${scoreline(i.score, teams)}` : ''}`}
            >
              <span
                className={`grid place-items-center rounded-full bg-ink-800 ${expanded ? 'size-6 ring-2' : 'size-4 ring-[1.5px]'} ${i.team_id === teams[0].id ? 'ring-home/70' : 'ring-away/70'} ${cancelled.has(i.id) ? 'opacity-40' : ''}`}
              >
                <IncidentIcon icon={INCIDENTS[i.kind].icon} className={expanded ? 'size-3.5' : 'size-2.5'} />
              </span>
            </Marker>
          ))}
        </ul>
        <ul aria-label="Alerts">
          {alerts.map((a, n) => (
            <Marker key={a.id} left={left(axis.x(a))} align={align(fraction(axis.x(a)))} top={L.alertTop(alertLanes[n])} label={`${matchClock(a)} · ${ALERT_NAMES[a.type]} · ${a.message}`}>
              <span className={`grid place-items-center rounded-full text-ink-950 ${colour(a.team_id)} ${expanded ? 'size-4' : 'size-2.5'}`}>
                {expanded && <AlertIcon type={a.type} className="size-2.5" />}
              </span>
            </Marker>
          ))}
        </ul>
      </div>
    </figure>
  )
}

/** Where markers go: expanded, in stacked lanes; compact, one row of smaller ones. */
interface Layout {
  lanes: number
  midline: number
  height: number
  periodTick: number
  eventTop: (lane: number) => number
  alertTop: (lane: number) => number
}

const FULL_MIDLINE = 30 + (LANES - 1) * 26 + 4
const FULL: Layout = {
  lanes: LANES,
  midline: FULL_MIDLINE,
  height: FULL_MIDLINE + 6 + LANES * 18 + 16,
  periodTick: 16,
  eventTop: (lane) => FULL_MIDLINE - 30 - lane * 26,
  alertTop: (lane) => FULL_MIDLINE + 6 + lane * 18,
}
const COMPACT_MIDLINE = 22
const COMPACT: Layout = {
  lanes: 1,
  midline: COMPACT_MIDLINE,
  height: COMPACT_MIDLINE + 16 + 14,
  periodTick: 10,
  eventTop: () => COMPACT_MIDLINE - 20,
  alertTop: () => COMPACT_MIDLINE + 4,
}
/** The closest two markers in a lane may be, as a share of the strip's width. */
const EVENT_GAP = 0.03
const ALERT_GAP = 0.02

/** Which way a tooltip hangs, so the ones near either end stay on screen. */
type Align = 'start' | 'center' | 'end'

const align = (fraction: number): Align => (fraction < 0.2 ? 'start' : fraction > 0.8 ? 'end' : 'center')

const ALIGN: Record<Align, string> = { start: 'left-0', center: 'left-1/2 -translate-x-1/2', end: 'right-0' }

function Marker({ left, top, align, above = false, label, children }: { left: string; top: number; align: Align; above?: boolean; label: string; children: ReactNode }) {
  return (
    <li className="group absolute -translate-x-1/2 hover:z-30 focus-within:z-30" style={{ left, top }}>
      <button type="button" aria-label={label} className="block rounded-full transition hover:scale-125 focus-visible:scale-125">
        {children}
      </button>
      <span
        role="tooltip"
        className={`pointer-events-none invisible absolute z-20 w-max max-w-64 rounded-lg ${ALIGN[align]} border border-white/10 bg-ink-800 px-2.5 py-1.5 text-xs text-slate-100 opacity-0 shadow-xl transition group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100 ${above ? 'bottom-full mb-1.5' : 'top-full mt-1.5'}`}
      >
        {label}
      </span>
    </li>
  )
}
