import { useMemo } from 'react'
import { AlertFeed } from './AlertFeed'
import { matchTeams } from './chartData'
import { MatchPicker } from './MatchPicker'
import { MetricCharts } from './MetricCharts'
import { BroadcastControls } from './BroadcastControls'
import { StatusBar } from './StatusBar'
import { useMatchStream } from './useMatchStream'
import { useBroadcast, type Broadcast } from './useBroadcast'
import { useViewer } from './useViewer'
import { ViewerControls } from './ViewerControls'

export default function App() {
  const match = useMatchStream()
  const broadcast = useBroadcast(match.status?.state)
  const viewer = useViewer()
  // Hidden only once the engine says there is no simulator, so its errors still show.
  const simulator = broadcast.controllable !== false
  const teams = useMemo(() => matchTeams(match.status, broadcast.matches), [match.status, broadcast.matches])

  return (
    <div className="mx-auto flex min-h-screen max-w-7xl flex-col gap-4 p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-xl font-semibold">Live Football Analytics</h1>
        <StatusBar connection={match.connection} status={match.status} />
      </header>
      {simulator && (
        <section
          aria-label="Simulator"
          aria-describedby="simulator-note"
          className="flex flex-col gap-2 rounded-lg border border-dashed border-slate-700 p-3"
        >
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 className={groupHeading}>Simulator</h2>
            <p id="simulator-note" className="text-xs text-slate-500">
              Stands in for the live feed: picks the match and plays its broadcast. A real feed has none of this.
            </p>
          </div>
          <div role="group" aria-label="Broadcast" className="flex flex-wrap items-center gap-3">
            <MatchPicker
              matches={broadcast.matches}
              matchId={broadcast.status?.match_id}
              disabled={broadcast.pending}
              onLoad={(match_id) => void loadAndPlay(broadcast, match_id)}
            />
            <BroadcastControls status={broadcast.status} disabled={broadcast.pending} onCommand={broadcast.send} />
            <ErrorMessage message={broadcast.error} />
          </div>
        </section>
      )}
      <section aria-label="Controls" className="rounded-lg bg-slate-900 p-3">
        <div role="group" aria-label="Viewer" className="flex flex-wrap items-center gap-3">
          <h2 className={groupHeading}>Viewer</h2>
          <ViewerControls status={match.status} disabled={viewer.pending} onCommand={viewer.send} />
          <ErrorMessage message={viewer.error} />
        </div>
      </section>
      <main className="grid flex-1 gap-4 lg:grid-cols-[1fr_22rem]">
        <section aria-label="Charts" className="rounded-lg bg-slate-900 p-4">
          <MetricCharts
            teams={teams}
            snapshots={match.snapshots}
            alerts={match.alerts}
            broadcastState={broadcast.status?.state}
            simulator={simulator}
          />
        </section>
        <aside aria-label="Alerts" className="rounded-lg bg-slate-900 p-4">
          <AlertFeed teams={teams} alerts={match.alerts} />
        </aside>
      </main>
    </div>
  )
}

/** Choosing a match puts it on air, as on a real feed; Pause stops it. */
async function loadAndPlay(broadcast: Broadcast, match_id: number) {
  if (await broadcast.send({ command: 'load_match', match_id })) {
    await broadcast.send({ command: 'play' })
  }
}

const groupHeading = 'w-20 text-xs font-semibold tracking-wide text-slate-400 uppercase'

function ErrorMessage({ message }: { message: string | null }) {
  return (
    message && (
      <p role="alert" className="text-sm text-red-400">
        {message}
      </p>
    )
  )
}
