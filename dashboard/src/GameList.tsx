import type { MarketGame, Venue } from './schema/market_board.schema'
import { VENUE_ORDER, VENUES } from './venues'

interface Props {
  games: MarketGame[]
  selected?: string
  onSelect: (id: string) => void
  /** For grouping by day; the time now. */
  now: number
}

/** The league's games, live first, then by day, each with the venues that list it. */
export function GameList({ games, selected, onSelect, now }: Props) {
  if (games.length === 0) {
    return <p className="py-10 text-center text-sm text-slate-400">No games listed right now.</p>
  }
  const groups: { title: string; games: MarketGame[] }[] = []
  for (const g of games) {
    const title = g.state === 'live' ? 'Live' : g.state === 'ended' ? 'Finished' : day(g.kickoff, now)
    const last = groups.at(-1)
    if (last?.title === title) last.games.push(g)
    else groups.push({ title, games: [g] })
  }
  return (
    <nav aria-label="Games" className="flex flex-col gap-4">
      {groups.map((group) => (
        <section key={group.title} aria-label={group.title}>
          <h3 className="eyebrow mb-2 flex items-center gap-2">
            {group.title === 'Live' && <span className="size-1.5 animate-live rounded-full bg-red-500" />}
            {group.title}
          </h3>
          <ul className="flex flex-col gap-1.5">
            {group.games.map((g) => (
              <li key={g.id}>
                <GameRow game={g} selected={g.id === selected} onSelect={() => onSelect(g.id)} />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </nav>
  )
}

function GameRow({ game: g, selected, onSelect }: { game: MarketGame; selected: boolean; onSelect: () => void }) {
  const listed = new Set<Venue>(g.listings.map((l) => l.venue))
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? 'true' : undefined}
      className="flex w-full items-center gap-3 rounded-xl border border-transparent bg-white/[0.03] px-3 py-2 text-left transition hover:bg-white/[0.06] aria-[current=true]:border-sky-400/30 aria-[current=true]:bg-sky-400/[0.08]"
    >
      <span className="w-12 shrink-0 font-mono text-xs tabular-nums">
        {g.state === 'live' ? <span className="font-semibold text-red-300">{g.clock ?? 'LIVE'}</span> : <span className="text-slate-400">{time(g.kickoff)}</span>}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5 text-sm">
        <TeamLine name={g.home.name} color={g.home.color} goals={g.score?.home} />
        <TeamLine name={g.away.name} color={g.away.color} goals={g.score?.away} />
      </span>
      <span className="flex shrink-0 gap-0.5" aria-label={`Listed on ${[...listed].map((v) => VENUES[v].name).join(', ')}`}>
        {VENUE_ORDER.map((v) => (
          <span
            key={v}
            aria-hidden="true"
            className={`grid size-4 place-items-center rounded text-[9px] font-bold ${listed.has(v) ? `bg-white/10 ${VENUES[v].text}` : 'text-slate-700'}`}
          >
            {VENUES[v].letter}
          </span>
        ))}
      </span>
    </button>
  )
}

function TeamLine({ name, color, goals }: { name: string; color?: string; goals?: number }) {
  return (
    <span className="flex items-center gap-2">
      <span className="size-2 shrink-0 rounded-full bg-slate-500" style={color ? { background: color } : undefined} />
      <span className="truncate">{name}</span>
      {goals !== undefined && <span className="ml-auto font-mono font-semibold tabular-nums">{goals}</span>}
    </span>
  )
}

const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })

/** "Today", "Tomorrow", or the weekday and date. */
function day(iso: string, now: number) {
  const d = new Date(iso)
  const startOf = (t: Date) => new Date(t.getFullYear(), t.getMonth(), t.getDate()).getTime()
  const days = Math.round((startOf(d) - startOf(new Date(now))) / 86_400_000)
  if (days === 0) return 'Today'
  if (days === 1) return 'Tomorrow'
  return d.toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' })
}
