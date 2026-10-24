import { VENUE_ORDER, VENUES } from './venues'

/**
 * What paper trading will look like: the controls are here, but off, until the
 * live event feed gives the model something to price live games with.
 */
export function PaperTrading() {
  return (
    <section aria-label="Paper trading" aria-describedby="paper-trading-note" className="card flex flex-col gap-3 p-4">
      <header className="flex items-center justify-between gap-2">
        <h3 className="font-semibold">Paper trading</h3>
        <span className="rounded-full border border-amber-400/30 bg-amber-400/10 px-2 py-0.5 text-[11px] font-semibold text-amber-200">
          Coming with the live feed
        </span>
      </header>
      <p id="paper-trading-note" className="text-sm text-slate-400">
        When an alert fires, buy the contract it bears on wherever its all-in price is lowest, if our model's chance beats that price by the margin.
        Paper trades fill against the real order book and settle at full time; no money moves.
      </p>
      <fieldset disabled className="grid gap-3 opacity-60 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Stake a trade
          <input className="rounded-lg border border-white/10 bg-ink-800 px-2 py-1.5 text-sm text-slate-200" defaultValue="$5" />
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Budget this game
          <input className="rounded-lg border border-white/10 bg-ink-800 px-2 py-1.5 text-sm text-slate-200" defaultValue="$20" />
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Edge required
          <input className="rounded-lg border border-white/10 bg-ink-800 px-2 py-1.5 text-sm text-slate-200" defaultValue="4¢" />
        </label>
        <div className="flex flex-wrap items-center gap-3 sm:col-span-3">
          {VENUE_ORDER.map((v) => (
            <label key={v} className="flex items-center gap-1.5 text-sm">
              <input type="checkbox" defaultChecked /> <span className={VENUES[v].text}>{VENUES[v].name}</span>
            </label>
          ))}
          <button type="button" className="ml-auto rounded-lg bg-sky-500/20 px-3 py-1.5 text-sm font-semibold text-sky-100">
            Start paper trading
          </button>
        </div>
      </fieldset>
      <p role="note" className="rounded-lg border border-amber-400/20 bg-amber-400/[0.06] px-3 py-2 text-xs text-amber-100/80">
        <span className="font-semibold text-amber-200">Real money runs only on your own machine</span> (<code>make up</code>), never in the cloud
        deployment: each venue's key is pasted for one game, held in memory only, and never stored.
      </p>
    </section>
  )
}
