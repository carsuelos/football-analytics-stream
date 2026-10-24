import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from 'recharts'
import type { Contract, Venue } from './schema/market_board.schema'
import type { PriceHistory } from './schema/price_history.schema'
import { cents, VENUES } from './venues'

const DOT: Record<Venue, string> = { kalshi: '#34d399', polymarket: '#38bdf8', novig: '#a78bfa' }

interface Props {
  contract?: Contract
  history: PriceHistory | null
}

/** The best all-in price of one contract over time, each point coloured by the venue that had it. */
export function PriceChart({ contract, history }: Props) {
  const points = (contract && history?.series.find((s) => s.key === contract.key)?.points) || []
  const data = points.map((p) => ({ t: Date.parse(p.t), price: p.all_in * 100, venue: p.venue }))
  return (
    <section aria-label="Price over time" className="card p-4">
      <header className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold">
          Best all-in price{contract && <span className="text-slate-400"> · {contract.label}</span>}
        </h3>
        <p className="text-xs text-slate-500">Click a contract above to follow it. Recorded while the markets service runs.</p>
      </header>
      {data.length < 2 ? (
        <p className="py-10 text-center text-sm text-slate-400">Collecting prices: a point every poll while it changes.</p>
      ) : (
        <figure aria-label="Best all-in price" className="m-0">
          <LineChart responsive data={data} style={{ width: '100%', height: 200 }} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              domain={['dataMin', 'dataMax']}
              tickFormatter={(t: number) => new Date(t).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
              stroke="#475569"
              tickLine={false}
              axisLine={false}
              fontSize={11}
            />
            <YAxis stroke="#475569" tickLine={false} axisLine={false} fontSize={11} tickFormatter={(v: number) => cents(v / 100)} domain={['auto', 'auto']} />
            <Tooltip
              content={({ active, payload }) => {
                const p = payload?.[0]?.payload as (typeof data)[number] | undefined
                if (!active || !p) return null
                return (
                  <div className="rounded-lg border border-white/10 bg-ink-800/95 px-2.5 py-1.5 text-xs shadow-xl">
                    <p className="text-slate-400">{new Date(p.t).toLocaleTimeString()}</p>
                    <p>
                      <span className="font-mono font-semibold">{cents(p.price / 100)}</span> on{' '}
                      <span className={VENUES[p.venue].text}>{VENUES[p.venue].name}</span>
                    </p>
                  </div>
                )
              }}
            />
            <Line
              dataKey="price"
              type="stepAfter"
              stroke="#94a3b8"
              strokeWidth={1.5}
              isAnimationActive={false}
              dot={({ cx, cy, payload, index }) => <circle key={index} cx={cx} cy={cy} r={2.5} fill={DOT[(payload as (typeof data)[number]).venue]} />}
            />
          </LineChart>
        </figure>
      )}
    </section>
  )
}
