import type { AlertType } from './schema/alert.schema'
import type { IncidentIcon as IconKind } from './incidents'

type SvgProps = { className?: string }

/** A football. */
export function BallIcon({ className = 'size-4' }: SvgProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="white" stroke="#0b0f1a" strokeWidth="1.2" />
      <path d="M12 7.2l3.6 2.6-1.4 4.2H9.8L8.4 9.8z" fill="#0b0f1a" />
      <path
        d="M12 7.2V3M15.6 9.8l4-1.4M14.2 14l2.6 3.6M9.8 14l-2.6 3.6M8.4 9.8l-4-1.4"
        stroke="#0b0f1a"
        strokeWidth="1.2"
        fill="none"
      />
    </svg>
  )
}

function CardIcon({ colour, second = false, className = 'size-4' }: SvgProps & { colour: string; second?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      {second && <rect x="4" y="3" width="11" height="15" rx="2" fill="#facc15" transform="rotate(-12 9 10)" />}
      <rect x={second ? 9 : 6.5} y="4" width="11" height="16" rx="2" fill={colour} />
    </svg>
  )
}

function PenaltyIcon({ className = 'size-4' }: SvgProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M3 6h18v9" />
      <path d="M3 6v9" />
      <path d="M6 6v5h12V6" />
      <circle cx="12" cy="19" r="1.6" fill="currentColor" />
    </svg>
  )
}

function MissedIcon({ className = 'size-4' }: SvgProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <circle cx="12" cy="12" r="9" fill="none" stroke="#94a3b8" strokeWidth="1.6" strokeDasharray="3 2.5" />
      <path d="M8.5 8.5l7 7M15.5 8.5l-7 7" stroke="#f87171" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

function VarIcon({ className = 'size-4' }: SvgProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <rect x="2.5" y="5" width="19" height="13" rx="2" fill="none" stroke="#a78bfa" strokeWidth="1.6" />
      <path d="M8 20h8" stroke="#a78bfa" strokeWidth="1.6" strokeLinecap="round" />
      <text x="12" y="14.6" textAnchor="middle" fontSize="7" fontWeight="700" fill="#a78bfa">
        VAR
      </text>
    </svg>
  )
}

/** The icon of an incident, e.g. a ball for a goal or a red card. */
export function IncidentIcon({ icon, className }: SvgProps & { icon: IconKind }) {
  switch (icon) {
    case 'goal':
      return <BallIcon className={className} />
    case 'own_goal':
      return (
        <span className="relative inline-flex">
          <BallIcon className={className} />
          <span className="absolute -right-1 -bottom-1 size-2 rounded-full bg-red-500 ring-2 ring-ink-900" />
        </span>
      )
    case 'yellow':
      return <CardIcon colour="#facc15" className={className} />
    case 'red':
      return <CardIcon colour="#ef4444" className={className} />
    case 'second_yellow':
      return <CardIcon colour="#ef4444" second className={className} />
    case 'penalty':
      return <PenaltyIcon className={className} />
    case 'missed':
      return <MissedIcon className={className} />
    case 'var':
      return <VarIcon className={className} />
  }
}

const ALERT_PATHS: Record<AlertType, string> = {
  // A rising line.
  momentum_shift: 'M3 17l6-6 4 4 8-8M15 7h6v6',
  // A target.
  goal_threat: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm0 4a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm0 4a1 1 0 1 0 0 2 1 1 0 0 0 0-2z',
  // A balance tipping.
  control_shift: 'M12 4v16M5 8l14-3M5 8l-3 6h6zM19 5l-3 6h6z',
  // A spark: the model.
  goal_chance: 'M12 2l2.2 6.6L21 11l-6.8 2.4L12 20l-2.2-6.6L3 11l6.8-2.4z',
}

/** The icon of an alert type. */
export function AlertIcon({ type, className = 'size-4' }: SvgProps & { type: AlertType }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={ALERT_PATHS[type]} />
    </svg>
  )
}

export function PlayIcon({ className = 'size-3.5' }: SvgProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" fill="currentColor">
      <path d="M7 4.5v15l13-7.5z" />
    </svg>
  )
}

export function PauseIcon({ className = 'size-3.5' }: SvgProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" fill="currentColor">
      <rect x="6" y="4.5" width="4" height="15" rx="1" />
      <rect x="14" y="4.5" width="4" height="15" rx="1" />
    </svg>
  )
}
