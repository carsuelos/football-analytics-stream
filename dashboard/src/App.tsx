import { AnalyticsPage } from './AnalyticsPage'
import { MarketsPage } from './MarketsPage'
import { ThemeToggle } from './ThemeToggle'
import { hrefOf, useRoute, type Route } from './useRoute'

const PAGES: { route: Route; label: string }[] = [
  { route: 'analytics', label: 'Match analytics' },
  { route: 'markets', label: 'Markets' },
]

/** The header and the page the URL is on. Only that page is mounted, so only it polls or streams. */
export default function App() {
  const route = useRoute()
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-white/[0.06] bg-ink-950/70 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[90rem] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-3">
            <Logo />
            <div className="leading-tight">
              <h1 className="text-[15px] font-semibold tracking-tight">Live Football Analytics</h1>
              <p className="text-xs text-slate-500">Momentum, threat and goal chances, as they happen</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <nav aria-label="Pages" className="flex items-center gap-1 rounded-xl border border-white/[0.06] bg-black/20 p-1">
              {PAGES.map((p) => (
                <a
                  key={p.route}
                  href={hrefOf(p.route)}
                  aria-current={route === p.route ? 'page' : undefined}
                  className="rounded-lg px-3 py-1.5 text-sm font-medium text-slate-400 transition hover:text-slate-100 aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
                >
                  {p.label}
                </a>
              ))}
            </nav>
            <ThemeToggle />
          </div>
        </div>
      </header>
      {route === 'markets' ? <MarketsPage /> : <AnalyticsPage />}
    </div>
  )
}

function Logo() {
  return (
    <span className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-home to-pitch shadow-lg shadow-home/20" aria-hidden="true">
      <svg viewBox="0 0 24 24" className="size-5 text-ink-950" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 17l5-5 4 3 9-9" />
        <path d="M16 6h5v5" />
      </svg>
    </span>
  )
}
