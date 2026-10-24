import { useMemo, useState } from 'react'
import { GameList } from './GameList'
import { GameMarkets } from './GameMarkets'
import { getBoard, getHistory } from './marketsApi'
import { Trading } from './Trading'
import { PriceChart } from './PriceChart'
import type { League, MarketBoard, VenueStatus } from './schema/market_board.schema'
import { usePolled } from './usePolled'
import { segmentClass, segmentsClass } from './ui'
import { ago, VENUES } from './venues'

const LEAGUES: { league: League; name: string }[] = [
  { league: 'epl', name: 'Premier League' },
  { league: 'laliga', name: 'La Liga' },
]

/** How often to ask for the board; the markets service polls the venues every 10s. */
export const BOARD_POLL_MS = 5000
const HISTORY_POLL_MS = 15000

/**
 * The prediction markets for a league's games: which venues list each game,
 * their prices for the same contracts, and the cheapest all-in. The live score
 * and clock come from the venues, not from our feed.
 */
export function MarketsPage() {
  const [league, setLeague] = useState<League>('epl')
  const board = usePolled(league, (signal) => getBoard(league, signal), BOARD_POLL_MS)
  const [chosenGame, setChosenGame] = useState<string>()
  const games = board.data?.games ?? []
  const game = games.find((g) => g.id === chosenGame) ?? games[0]
  const history = usePolled(game?.id ?? null, (signal) => getHistory(game!.id, signal), HISTORY_POLL_MS)
  const [chosenContract, setChosenContract] = useState<string>()
  const contract = useMemo(() => {
    if (!game) return undefined
    return (
      game.contracts.find((c) => c.key === chosenContract) ??
      // By default the total-goals line the market is least sure of.
      game.contracts.filter((c) => c.kind === 'total' && c.implied !== undefined).sort((a, b) => Math.abs(a.implied! - 0.5) - Math.abs(b.implied! - 0.5))[0] ??
      game.contracts[0]
    )
  }, [game, chosenContract])
  // The board's own time, so ages and days don't depend on when this renders.
  const now = board.data ? Date.parse(board.data.updated_at) : 0

  return (
    <main className="mx-auto flex max-w-[90rem] flex-col gap-5 px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label="League" className={segmentsClass}>
          {LEAGUES.map((l) => (
            <button key={l.league} type="button" className={segmentClass} aria-pressed={league === l.league} onClick={() => setLeague(l.league)}>
              {l.name}
            </button>
          ))}
        </div>
        {board.data && <Venues board={board.data} now={now} />}
      </div>
      {board.error && (
        <p role="alert" className="rounded-xl border border-red-400/20 bg-red-400/10 px-4 py-2 text-sm text-red-300">
          {board.error}
          {board.data && ' (showing the last prices)'}
        </p>
      )}
      {!board.data ? (
        !board.error && <p className="py-16 text-center text-slate-400">Loading the markets…</p>
      ) : (
        <div className="grid items-start gap-5 lg:grid-cols-[20rem_minmax(0,1fr)]">
          {/* On a narrow screen the list scrolls by itself, so the prices stay near. */}
          <aside aria-label="Game list" className="card max-h-[22rem] overflow-y-auto p-3 lg:sticky lg:top-24 lg:max-h-[calc(100vh-7rem)]">
            <GameList games={games} selected={game?.id} onSelect={(id) => (setChosenGame(id), setChosenContract(undefined))} now={now} />
          </aside>
          {game ? (
            <div className="flex min-w-0 flex-col gap-5">
              <GameMarkets game={game} selected={contract?.key} onSelect={setChosenContract} />
              <PriceChart contract={contract} history={history.data} />
              <Trading />
              <p className="text-xs text-slate-500">
                All-in = the ask plus the venue's taker fee per contract: Kalshi {VENUES.kalshi.fee}, Polymarket {VENUES.polymarket.fee}, Novig{' '}
                {VENUES.novig.fee}. Every price is for a contract paying $1 (Novig's pay 1¢, so its sizes are divided by 100).
              </p>
            </div>
          ) : (
            <p className="card py-16 text-center text-slate-400">No games listed for this league right now.</p>
          )}
        </div>
      )}
    </main>
  )
}

function Venues({ board, now }: { board: MarketBoard; now: number }) {
  return (
    <ul aria-label="Venues" className="flex flex-wrap gap-2">
      {board.venues.map((v) => (
        <li key={v.venue}>
          <VenueChip status={v} now={now} />
        </li>
      ))}
    </ul>
  )
}

function VenueChip({ status: v, now }: { status: VenueStatus; now: number }) {
  const meta = VENUES[v.venue]
  return (
    <span
      title={v.error ?? undefined}
      className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${v.ok ? 'border-white/10 bg-white/[0.03]' : 'border-red-400/30 bg-red-400/10'}`}
    >
      <span className={`size-1.5 rounded-full ${v.ok ? meta.dot : 'bg-red-400'}`} />
      <span className={meta.text}>{meta.name}</span>
      <span className="text-slate-400">
        {v.games} games{v.updated_at && ` · ${ago(v.updated_at, now)}`}
        {!v.ok && ' · failing'}
      </span>
    </span>
  )
}
