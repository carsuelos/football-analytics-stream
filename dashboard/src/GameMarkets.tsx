import { useId, useRef, useState, type DragEvent, type KeyboardEvent } from 'react'
import { ChevronIcon, GripIcon } from './Icons'
import type { Contract, ContractKind, MarketGame, Quote } from './schema/market_board.schema'
import { useStoredFlag, useStoredOrder } from './useStored'
import { cents, percent, VENUE_ORDER, VENUES } from './venues'

interface Props {
  game: MarketGame
  /** The contract the price chart is following. */
  selected?: string
  onSelect: (key: string) => void
}

/**
 * One game's contracts, priced on each venue: the ask (to buy Yes now), the
 * bid and the fee, and the cheapest all-in across the venues, which is where
 * a trade would go. Our model's probability joins them with the live feed.
 */
export function GameMarkets({ game: g, selected, onSelect }: Props) {
  const [order, setOrder] = useStoredOrder('markets.sections', SECTION_IDS)
  const [dragging, setDragging] = useState<SectionId | null>(null)
  const goals = g.score ? g.score.home + g.score.away : 0
  const decided: Record<SectionId, (c: Contract) => boolean> = {
    result: () => false,
    total: (c) => c.line !== undefined && c.line < goals,
    team_total: (c) => c.line !== undefined && g.score !== undefined && c.line < (c.outcome === 'home' ? g.score.home : g.score.away),
  }
  /** Puts a section where another is, shifting the rest. */
  const move = (id: SectionId, to: number) => {
    const next = order.filter((o) => o !== id)
    next.splice(Math.max(0, Math.min(to, next.length)), 0, id)
    setOrder(next)
  }
  return (
    <div className="flex flex-col gap-5">
      <GameHeader game={g} />
      {order.map((id, index) => (
        <ContractTable
          key={id}
          title={SECTIONS[id]}
          contracts={g.contracts.filter((c) => c.kind === id)}
          decided={decided[id]}
          selected={selected}
          onSelect={onSelect}
          reorder={{
            index,
            count: order.length,
            dragging: dragging !== null,
            onDragStart: () => setDragging(id),
            onDragEnd: () => setDragging(null),
            onDrop: () => dragging && dragging !== id && move(dragging, index),
            onMove: (to) => move(id, to),
          }}
        />
      ))}
    </div>
  )
}

/** The kinds of contract, each a section the viewer can fold and reorder: by default the result first. */
const SECTIONS = { result: 'Result', total: 'Total goals', team_total: 'Team goals' } as const satisfies Record<ContractKind, string>
type SectionId = keyof typeof SECTIONS
const SECTION_IDS = Object.keys(SECTIONS) as SectionId[]

function GameHeader({ game: g }: { game: MarketGame }) {
  const kickoff = new Date(g.kickoff)
  return (
    <section aria-label="Game" className="flex flex-col gap-3 rounded-xl border border-white/[0.06] bg-ink-950/60 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
      <div className="grid min-w-0 flex-1 grid-cols-[1fr_auto_1fr] items-center gap-3 sm:gap-4">
        <Team name={g.home.name} color={g.home.color} align="end" />
        <div className="flex flex-col items-center">
          {g.score ? (
            <p className="text-3xl leading-none font-bold tabular-nums">
              <span className="sr-only">
                Score: {g.home.name} {g.score.home}, {g.away.name} {g.score.away}
              </span>
              <span aria-hidden="true">
                {g.score.home} <span className="text-xl font-light text-slate-500">–</span> {g.score.away}
              </span>
            </p>
          ) : (
            <p className="text-sm font-semibold text-slate-300">
              {kickoff.toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })}
              {g.kickoff_estimated && <span title="Only Kalshi lists this game, and it gives no kick-off time"> (est.)</span>}
            </p>
          )}
          {g.state === 'live' && (
            <span className="mt-1 flex items-center gap-1 rounded-full bg-red-500/15 px-2 py-0.5 text-[11px] font-bold tracking-wider text-red-300">
              <span className="size-1.5 animate-live rounded-full bg-red-500" /> {g.clock ?? 'LIVE'}
            </span>
          )}
        </div>
        <Team name={g.away.name} color={g.away.color} align="start" />
      </div>
      <ul aria-label="Listed on" className="flex flex-wrap justify-center gap-1.5">
        {VENUE_ORDER.filter((v) => g.listings.some((l) => l.venue === v)).map((v) => {
          const url = g.listings.find((l) => l.venue === v)?.url
          const label = <span className={VENUES[v].text}>{VENUES[v].name}</span>
          return (
            <li key={v} className="rounded-full border border-white/10 px-2.5 py-0.5 text-xs">
              {url ? (
                <a href={url} target="_blank" rel="noreferrer" className="hover:underline">
                  {label} ↗
                </a>
              ) : (
                label
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function Team({ name, color, align }: { name: string; color?: string; align: 'start' | 'end' }) {
  return (
    <span className={`flex min-w-0 items-center gap-2 ${align === 'end' ? 'flex-row-reverse text-right' : ''}`}>
      <span className="size-3 shrink-0 rounded-full bg-slate-500" style={color ? { background: color } : undefined} />
      <span className="truncate text-base font-semibold sm:text-lg">{name}</span>
    </span>
  )
}

interface Reorder {
  index: number
  count: number
  /** Whether any section is being dragged (each section is then a drop target). */
  dragging: boolean
  onDragStart: () => void
  onDragEnd: () => void
  onDrop: () => void
  /** Moves this section to a position (the arrow keys on its handle). */
  onMove: (to: number) => void
}

interface TableProps {
  title: string
  contracts: Contract[]
  /** Contracts already settled by the score: a line the goals have passed. */
  decided: (c: Contract) => boolean
  selected?: string
  onSelect: (key: string) => void
  reorder: Reorder
}

/**
 * A kind of contract: foldable, and movable by its handle (drag it, or focus
 * it and use the arrow keys). Both are remembered across games and visits.
 */
function ContractTable({ title, contracts, decided, selected, onSelect, reorder: r }: TableProps) {
  const [open, setOpen] = useStoredFlag(`markets.open.${title}`, true)
  const [over, setOver] = useState(false)
  const section = useRef<HTMLElement>(null)
  const body = useId()
  const dragStart = (e: DragEvent) => {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', title)
    if (section.current) e.dataTransfer.setDragImage(section.current, 24, 24)
    r.onDragStart()
  }
  const keyDown = (e: KeyboardEvent) => {
    const to = { ArrowUp: r.index - 1, ArrowDown: r.index + 1, Home: 0, End: r.count - 1 }[e.key]
    if (to === undefined) return
    e.preventDefault()
    if (to >= 0 && to < r.count && to !== r.index) r.onMove(to)
  }
  return (
    <section
      ref={section}
      aria-label={title}
      className={`card overflow-hidden transition ${over ? 'ring-2 ring-sky-400/50' : ''}`}
      onDragOver={(e) => {
        if (!r.dragging) return
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        r.onDrop()
      }}
    >
      <header className={`flex items-center gap-1 px-2 pt-2 ${open ? 'pb-1' : 'pb-2'}`}>
        <button
          type="button"
          draggable
          onDragStart={dragStart}
          onDragEnd={r.onDragEnd}
          onKeyDown={keyDown}
          aria-label={`Move ${title}`}
          aria-description={`Position ${r.index + 1} of ${r.count}. Drag, or use the up and down arrow keys.`}
          title="Drag to reorder (or focus and use ↑ ↓)"
          className="grid size-7 cursor-grab place-items-center rounded-md text-slate-600 transition hover:bg-white/[0.05] hover:text-slate-300 active:cursor-grabbing"
        >
          <GripIcon className="size-4" />
        </button>
        <h3>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={body}
            onClick={() => setOpen(!open)}
            className="flex items-center gap-1.5 rounded-lg px-1.5 py-1 font-semibold transition hover:bg-white/[0.04]"
          >
            <ChevronIcon className={`size-4 text-slate-400 transition-transform ${open ? '' : '-rotate-90'}`} />
            {title}{' '}
            <span className="text-xs font-normal text-slate-500 tabular-nums">
              {contracts.length} <span className="sr-only">contracts</span>
            </span>
          </button>
        </h3>
      </header>
      {!open ? null : contracts.length === 0 ? (
        <p id={body} className="px-4 pb-4 text-sm text-slate-400">
          No venue lists these for this game.
        </p>
      ) : (
        <div id={body} className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead>
              <tr className="text-left text-[11px] tracking-wider text-slate-500 uppercase">
                <th className="px-4 py-2 font-semibold">Contract</th>
                {VENUE_ORDER.map((v) => (
                  <th key={v} className={`px-3 py-2 text-right font-semibold ${VENUES[v].text}`}>
                    {VENUES[v].name}
                  </th>
                ))}
                <th className="px-3 py-2 text-right font-semibold text-slate-300">Best all-in</th>
                <th className="px-4 py-2 text-right font-semibold" title="Our model's chance of this, from the live event feed (the next phase)">
                  Our model
                </th>
              </tr>
            </thead>
            <tbody>
              {contracts.map((c) => (
                <ContractRow key={c.key} contract={c} decided={decided(c)} selected={c.key === selected} onSelect={() => onSelect(c.key)} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function ContractRow({ contract: c, decided, selected, onSelect }: { contract: Contract; decided: boolean; selected: boolean; onSelect: () => void }) {
  return (
    <tr
      onClick={onSelect}
      aria-selected={selected}
      className={`cursor-pointer border-t border-white/[0.05] transition hover:bg-white/[0.03] aria-selected:bg-sky-400/[0.06] ${decided ? 'opacity-40' : ''}`}
    >
      <th scope="row" className="px-4 py-2.5 text-left font-medium">
        {c.label}
        {decided && <span className="ml-2 text-[11px] font-normal text-slate-400">already over</span>}
      </th>
      {VENUE_ORDER.map((v) => (
        <PriceCell key={v} quote={c.quotes.find((q) => q.venue === v)} best={c.best === v} />
      ))}
      <td className="px-3 py-2.5 text-right">
        {c.best && c.implied !== undefined ? (
          <span className="flex flex-col items-end leading-tight">
            <span className="font-mono font-semibold tabular-nums">{cents(c.implied)}</span>
            <span className="text-[11px] text-slate-400">
              {percent(c.implied)} · <span className={VENUES[c.best].text}>{VENUES[c.best].name}</span>
            </span>
          </span>
        ) : (
          <span className="text-slate-600">—</span>
        )}
      </td>
      <td className="px-4 py-2.5 text-right text-slate-600" title="Needs the live event feed">
        —
      </td>
    </tr>
  )
}

function PriceCell({ quote: q, best }: { quote?: Quote; best: boolean }) {
  if (!q) {
    return (
      <td className="px-3 py-2.5 text-right text-xs text-slate-700" title="Not listed">
        —
      </td>
    )
  }
  return (
    <td className="px-3 py-2.5 text-right">
      <span
        className={`inline-flex flex-col items-end rounded-lg px-2 py-1 leading-tight ${best ? 'bg-emerald-400/10 ring-1 ring-emerald-400/40' : ''}`}
        title={best ? 'Cheapest all-in' : undefined}
      >
        <span className="font-mono font-semibold tabular-nums">{q.ask !== undefined ? cents(q.ask) : <span className="text-slate-500">no offer</span>}</span>
        <span className="text-[11px] whitespace-nowrap text-slate-500 tabular-nums">
          {q.bid !== undefined ? `bid ${cents(q.bid)}` : 'no bid'}
          {q.fee !== undefined && q.fee > 0 && ` · fee ${cents(q.fee)}`}
        </span>
      </span>
    </td>
  )
}
