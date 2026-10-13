import { useMemo } from 'react'
import { AlertFeed } from './AlertFeed'
import { matchTeams } from './chartData'
import { MatchPicker } from './MatchPicker'
import { MetricCharts } from './MetricCharts'
import { PlaybackControls } from './PlaybackControls'
import { StatusBar } from './StatusBar'
import { useMatchStream } from './useMatchStream'
import { usePlayback } from './usePlayback'

export default function App() {
  const match = useMatchStream()
  const playback = usePlayback(match.status?.state)
  const teams = useMemo(() => matchTeams(match.status, playback.matches), [match.status, playback.matches])

  return (
    <div className="mx-auto flex min-h-screen max-w-7xl flex-col gap-4 p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-xl font-semibold">Live Football Analytics</h1>
        <StatusBar connection={match.connection} status={match.status} />
      </header>
      <section aria-label="Playback" className="flex flex-wrap items-center gap-3 rounded-lg bg-slate-900 p-3">
        <MatchPicker
          matches={playback.matches}
          matchId={playback.status?.match_id}
          disabled={playback.pending}
          onLoad={(match_id) => playback.send({ command: 'load_match', match_id })}
        />
        <PlaybackControls status={playback.status} disabled={playback.pending} onCommand={playback.send} />
        {playback.error && (
          <p role="alert" className="text-sm text-red-400">
            {playback.error}
          </p>
        )}
      </section>
      <main className="grid flex-1 gap-4 lg:grid-cols-[1fr_22rem]">
        <section aria-label="Charts" className="rounded-lg bg-slate-900 p-4">
          <MetricCharts teams={teams} snapshots={match.snapshots} alerts={match.alerts} />
        </section>
        <aside aria-label="Alerts" className="rounded-lg bg-slate-900 p-4">
          <AlertFeed teams={teams} alerts={match.alerts} />
        </aside>
      </main>
    </div>
  )
}
