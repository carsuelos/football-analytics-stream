import type { ReactNode } from 'react'
import { AlertIcon, IncidentIcon } from './Icons'
import { cancelledGoals, describe, INCIDENTS, isGoal, scoreline } from './incidents'
import { ALERT_NAMES } from './alerts'
import { LANES, lanes } from './lanes'
import type { Alert } from './schema/alert.schema'
import type { Team } from './schema/engine_status.schema'
import type { Incident } from './schema/incident.schema'
import { matchClock, type Timeline } from './timeline'

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
 */
export function EventStrip({ teams, incidents, alerts, axis, now }: Props) {
  const [start, end] = axis.domain
  const fraction = (x: number) => (x - start) / (end - start)
  const left = (x: number) => `${fraction(x) * 100}%`
  const cancelled = cancelledGoals(incidents)
  // The shootout has no place on the timeline of play.
  const events = incidents.filter((i) => i.period !== 5)
  const colour = (team_id: number) => (team_id === teams[0].id ? 'bg-home' : 'bg-away')
  const eventLanes = lanes(events.map((i) => fraction(axis.x(i))), EVENT_GAP)
  const alertLanes = lanes(alerts.map((a) => fraction(axis.x(a))), ALERT_GAP)

  return (
    <figure aria-label="Match timeline" className="flex flex-col gap-1">
      <figcaption className="eyebrow">Match timeline</figcaption>
      <div className="relative" style={{ height: HEIGHT }}>
        <div className="absolute inset-x-0 h-px bg-white/10" style={{ top: MIDLINE }} />
        {now !== undefined && (
          <div className="absolute left-0 h-0.5 rounded-full bg-gradient-to-r from-sky-400/0 to-sky-400/80" style={{ top: MIDLINE - 0.5, width: left(Math.min(now, end)) }} />
        )}
        {axis.periodStarts.map((p) => (
          <div key={p.name} className="absolute w-px bg-white/10" style={{ left: left(p.x), top: MIDLINE - 16, height: 32 }} />
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
              top={MIDLINE - 30 - eventLanes[n] * 26}
              above
              label={`${matchClock(i)} · ${describe(i)}${cancelled.has(i.id) ? ' (disallowed)' : ''}${isGoal(i) ? ` · ${scoreline(i.score, teams)}` : ''}`}
            >
              <span className={`grid size-6 place-items-center rounded-full bg-ink-800 ring-2 ${i.team_id === teams[0].id ? 'ring-home/70' : 'ring-away/70'} ${cancelled.has(i.id) ? 'opacity-40' : ''}`}>
                <IncidentIcon icon={INCIDENTS[i.kind].icon} className="size-3.5" />
              </span>
            </Marker>
          ))}
        </ul>
        <ul aria-label="Alerts">
          {alerts.map((a, n) => (
            <Marker key={a.id} left={left(axis.x(a))} align={align(fraction(axis.x(a)))} top={MIDLINE + 6 + alertLanes[n] * 18} label={`${matchClock(a)} · ${ALERT_NAMES[a.type]} · ${a.message}`}>
              <span className={`grid size-4 place-items-center rounded-full text-ink-950 ${colour(a.team_id)}`}>
                <AlertIcon type={a.type} className="size-2.5" />
              </span>
            </Marker>
          ))}
        </ul>
      </div>
    </figure>
  )
}

const MIDLINE = 30 + (LANES - 1) * 26 + 4
const HEIGHT = MIDLINE + 6 + LANES * 18 + 16
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
