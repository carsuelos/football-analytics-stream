import { useState, type ReactNode } from 'react'
import { segmentClass, segmentsClass } from './ui'
import { VENUE_ORDER, VENUES } from './venues'
import type { Venue } from './schema/market_board.schema'

type Mode = 'paper' | 'real'

/**
 * How the app will trade a game: the same strategy on paper or with real money.
 * It's all here to see but off until the live event feed gives the model
 * something to price live games with; only the Paper / Real money switch works.
 */
export function Trading() {
  const [mode, setMode] = useState<Mode>('paper')
  return (
    <section aria-label="Trading" className="card flex flex-col gap-4 p-4 sm:p-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h3 className="font-semibold">Trading</h3>
          <div role="group" aria-label="Mode" className={segmentsClass}>
            {(['paper', 'real'] as const).map((m) => (
              <button key={m} type="button" className={segmentClass} aria-pressed={mode === m} onClick={() => setMode(m)}>
                {m === 'paper' ? 'Paper' : 'Real money'}
              </button>
            ))}
          </div>
        </div>
        <span className="rounded-full border border-amber-400/30 bg-amber-400/10 px-2 py-0.5 text-[11px] font-semibold text-amber-200">Off until the live feed</span>
      </header>
      <p className="text-sm text-slate-400">
        When an alert fires, the app compares the contracts it bears on (that team's next goal line, and the game's) on every venue, and buys the one whose
        all-in price is furthest below our model's chance, if it's below by at least the edge.{' '}
        {mode === 'paper' ? 'Paper trades fill against the real order book and settle at full time; no money moves.' : 'Real orders are fill-or-cancel at that price.'}
      </p>
      <div className="grid gap-5 lg:grid-cols-2">
        <Strategy />
        {mode === 'paper' ? <PaperResults /> : <VenueKeys />}
      </div>
    </section>
  )
}

const inputBase = 'rounded-lg border border-white/10 bg-ink-800 px-2 py-1.5 text-sm text-slate-200'
const input = `${inputBase} w-full`

function Field({ label, children, wide = false }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <label className={`flex flex-col gap-1 text-xs text-slate-400 ${wide ? 'sm:col-span-3' : ''}`}>
      {label}
      {children}
    </label>
  )
}

/** What to buy, how much, and when to sell: the same for paper and real money. */
function Strategy() {
  return (
    <fieldset disabled aria-label="Strategy" className="grid content-start gap-3 opacity-70 sm:grid-cols-3">
      <legend className="eyebrow mb-2">Strategy</legend>
      <Field label="Stake a trade">
        <input className={input} defaultValue="$5" />
      </Field>
      <Field label="Budget this game">
        <input className={input} defaultValue="$20" />
      </Field>
      <Field label="Edge required">
        <input className={input} defaultValue="4¢" />
      </Field>
      <Field label="Buy" wide>
        <select className={input} defaultValue="best">
          <option value="best">The best edge: team goals or game goals</option>
          <option value="team">Team goals only</option>
          <option value="game">Game goals only</option>
        </select>
      </Field>
      <div className="flex flex-col gap-2 sm:col-span-3">
        <span className="text-xs text-slate-400">Sell before full time (otherwise hold)</span>
        <label className="flex flex-wrap items-center gap-2 text-sm">
          <input type="checkbox" /> Stop loss: sell if the bid falls to
          <input className={`${inputBase} w-16`} defaultValue="50%" aria-label="Stop loss, share of cost" /> of what it cost
        </label>
        <label className="flex flex-wrap items-center gap-2 text-sm">
          <input type="checkbox" /> Take profit: sell if the bid reaches
          <input className={`${inputBase} w-16`} defaultValue="150%" aria-label="Take profit, share of cost" /> of what it cost
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-3 sm:col-span-3">
        <span className="text-xs text-slate-400">Venues</span>
        {VENUE_ORDER.map((v) => (
          <label key={v} className="flex items-center gap-1.5 text-sm">
            <input type="checkbox" defaultChecked /> <span className={VENUES[v].text}>{VENUES[v].name}</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

function PaperResults() {
  const stats = [
    ['Trades', '0'],
    ['Won', '—'],
    ['P&L', '$0.00'],
    ['Average edge', '—'],
  ]
  return (
    <div className="flex flex-col gap-3">
      <h4 className="eyebrow">This game, on paper</h4>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {stats.map(([k, v]) => (
          <div key={k} className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2">
            <dt className="text-[11px] text-slate-500">{k}</dt>
            <dd className="font-mono text-lg font-semibold tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="rounded-xl border border-dashed border-white/10 px-3 py-6 text-center text-sm text-slate-500">
        Each trade will show here: what it bought, where and why, and how it settled.
      </p>
      <button type="button" disabled className="self-end rounded-lg bg-sky-500/20 px-3 py-1.5 text-sm font-semibold text-sky-100 opacity-60">
        Start paper trading
      </button>
    </div>
  )
}

/** What each venue's trading key is made of, and where to make one. */
const KEYS: Record<Venue, { id: string; secret: string; where: ReactNode }> = {
  kalshi: {
    id: 'API key ID',
    secret: 'Private key (RSA, PEM)',
    where: (
      <a href="https://kalshi.com/account/profile" target="_blank" rel="noreferrer" className="text-sky-300 hover:underline">
        Create one in your profile ↗
      </a>
    ),
  },
  polymarket: {
    id: 'API key',
    secret: 'Secret',
    where: (
      <a href="https://polymarket.us/developer" target="_blank" rel="noreferrer" className="text-sky-300 hover:underline">
        Create one on the developer page ↗
      </a>
    ),
  },
  novig: {
    id: 'Key ID',
    secret: 'Private key (Ed25519)',
    where: (
      <>
        <a href="https://novig.com/Profile/ProfileScreen" target="_blank" rel="noreferrer" className="text-sky-300 hover:underline">
          Create one in your profile settings ↗
        </a>{' '}
        — best a trading key on a sub-account funded with only this game's budget
      </>
    ),
  },
}

/** Real money: each venue's key, pasted for one game and forgotten at full time. */
function VenueKeys() {
  return (
    <div className="flex flex-col gap-3">
      <p role="note" className="rounded-lg border border-amber-400/20 bg-amber-400/[0.06] px-3 py-2 text-xs text-amber-100/80">
        <span className="font-semibold text-amber-200">Runs only on your own machine</span> (<code>make up</code>), never in the cloud deployment. Keys are held in
        memory for this game only: never saved, logged or sent anywhere but the venue, and forgotten at full time, on Stop, or on a restart.
      </p>
      <fieldset disabled aria-label="Venue keys" className="flex flex-col gap-3 opacity-70">
        <legend className="eyebrow mb-1">Venue keys</legend>
        {VENUE_ORDER.map((v) => (
          <fieldset key={v} aria-label={`${VENUES[v].name} key`} className="grid gap-2 rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 sm:grid-cols-2">
            <legend className="flex w-full items-baseline justify-between gap-2 px-1 text-sm">
              <span className={`font-semibold ${VENUES[v].text}`}>{VENUES[v].name}</span>
            </legend>
            <Field label={KEYS[v].id}>
              <input className={input} autoComplete="off" spellCheck={false} />
            </Field>
            <Field label={KEYS[v].secret}>
              <input type="password" className={input} autoComplete="off" />
            </Field>
            <p className="text-[11px] text-slate-500 sm:col-span-2">{KEYS[v].where}</p>
          </fieldset>
        ))}
        <label className="flex items-start gap-2 text-sm text-slate-300">
          <input type="checkbox" className="mt-1" />
          I authorize automated orders up to the budget on these venues for this game.
        </label>
        <div className="flex justify-end gap-2">
          <button type="button" className="rounded-lg border border-white/10 px-3 py-1.5 text-sm font-semibold text-slate-300">
            Stop and forget keys
          </button>
          <button type="button" className="rounded-lg bg-red-500/20 px-3 py-1.5 text-sm font-semibold text-red-100">
            Start real trading
          </button>
        </div>
      </fieldset>
    </div>
  )
}
