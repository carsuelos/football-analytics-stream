import { useMemo } from 'react'
import { BroadcastControls } from './BroadcastControls'
import { matchTeams } from './chartData'
import { EventStrip } from './EventStrip'
import { FeedDrawer } from './FeedDrawer'
import { MatchFeed } from './MatchFeed'
import { AddMatches } from './MatchLibrary'
import { MatchPicker } from './MatchPicker'
import { MetricCharts } from './MetricCharts'
import { AlertToasts } from './AlertToasts'
import { useAlertNotifications, useNotifySetting, useSoundSetting } from './notifications'
import { NotifySettings } from './NotifySettings'
import { Scoreboard } from './Scoreboard'
import { StatusBar } from './StatusBar'
import { teamColourStyle } from './teamColours'
import { timeline, type Position } from './timeline'
import { useBroadcast, type Broadcast } from './useBroadcast'
import { useMatchStream } from './useMatchStream'

/** The match analytics: the simulator or a live feed, through the engine. */
export function AnalyticsPage() {
  const match = useMatchStream()
  const broadcast = useBroadcast(match.status?.state)
  // Hidden only once the engine says there is no simulator, so its errors still show.
  const simulator = broadcast.controllable !== false
  const teams = useMemo(() => matchTeams(match.status, broadcast.matches), [match.status, broadcast.matches])
  const info = broadcast.matches?.find((m) => m.match_id === match.status?.match_id)
  const { period, match_clock_s } = match.status ?? {}
  const position = useMemo(() => viewerPosition(period, match_clock_s), [period, match_clock_s])
  // One axis for the strip, the charts and the feed. The shootout is not on it.
  const axis = useMemo(
    () => timeline([...match.snapshots, ...match.alerts, ...match.incidents.filter((i) => i.period !== 5), ...(position ? [position] : [])]),
    [match.snapshots, match.alerts, match.incidents, position],
  )
  // Play is over in the shootout and at full time: every alert's outcome is known.
  const over = period === 5 || match.status?.state === 'ended'
  const now = position ? axis.x(position) : period === 5 ? axis.domain[1] : undefined
  // How fast the match clock runs: the broadcast's pace (the engine's DVR, at /api/control, may run its own).
  const clockRate =
    match.status?.state === 'live'
      ? broadcast.status?.state === 'playing' || !simulator
        ? (broadcast.status?.speed ?? 1)
        : 0
      : match.status?.state === 'playing'
        ? (match.status.speed ?? 1)
        : 0
  const notify = useNotifySetting()
  const [sound, setSound] = useSoundSetting()
  const announced = useAlertNotifications({ system: notify.on, sound }, match.alerts, match.status, teams)

  return (
    <main className="mx-auto flex max-w-[90rem] flex-col gap-5 px-4 py-6 sm:px-6" style={teamColourStyle(teams)}>
        <AlertToasts toasts={announced.toasts} teams={teams} onDismiss={announced.dismiss} />
        <div className="flex items-center justify-end gap-2">
          <FeedDrawer count={match.alerts.length + match.incidents.length}>
            <MatchFeed teams={teams} alerts={match.alerts} incidents={match.incidents} axis={axis} now={now} over={over} />
          </FeedDrawer>
          <NotifySettings system={notify} sound={sound} onSound={setSound} onTest={announced.test} />
          <StatusBar connection={match.connection} status={match.status} />
        </div>
        {simulator && (
          <section aria-label="Replay" aria-describedby="replay-note" className="min-w-0 rounded-2xl border border-dashed border-white/10 px-4 py-3">
            <div role="group" aria-label="Broadcast" className="flex flex-wrap items-center gap-3">
              <h2 className={groupHeading}>Replay</h2>
              <MatchPicker
                matches={broadcast.matches}
                matchId={broadcast.status?.match_id}
                disabled={broadcast.pending}
                onLoad={(match_id) => void loadAndPlay(broadcast, match_id)}
              />
              <AddMatches onDownloaded={broadcast.refreshMatches} />
              <BroadcastControls status={broadcast.status} disabled={broadcast.pending} onCommand={broadcast.send} />
              <ErrorMessage message={broadcast.error} />
            </div>
            <p id="replay-note" className="mt-2 text-xs text-slate-500">
              Plays a past match as if it were live, at the speed you choose. With a live feed this panel isn't shown.
            </p>
          </section>
        )}
        <div className="grid flex-1 gap-5 lg:grid-cols-[minmax(0,1fr)_24rem]">
          <section aria-label="Charts" className="card flex flex-col gap-6 p-4 sm:p-5">
            {teams && (
              <div className="flex flex-col gap-3">
                {/* Stays in view while scrolling down the charts. */}
                <div className="sticky top-[4.5rem] z-20 -mx-1 rounded-xl bg-ink-900/85 px-1 py-1 backdrop-blur">
                  <Scoreboard teams={teams} status={match.status} incidents={match.incidents} connection={match.connection} info={info} rate={clockRate} />
                </div>
                <EventStrip teams={teams} incidents={match.incidents} alerts={match.alerts} axis={axis} now={now} />
              </div>
            )}
            <MetricCharts
              teams={teams}
              snapshots={match.snapshots}
              alerts={match.alerts}
              incidents={match.incidents}
              axis={axis}
              broadcastState={broadcast.status?.state}
              simulator={simulator}
            />
          </section>
          <aside aria-label="Match feed" className="card p-4 lg:sticky lg:top-24 lg:self-start">
            <MatchFeed teams={teams} alerts={match.alerts} incidents={match.incidents} axis={axis} now={now} over={over} />
          </aside>
        </div>
    </main>
  )
}

/** Where the viewer is in the match, unless it's before the first event or in the shootout. */
function viewerPosition(period?: number, match_clock_s?: number): Position | null {
  if (period === undefined || match_clock_s === undefined || period === 5) return null
  return { period, match_clock_s }
}

/** Choosing a match puts it on air, as on a real feed; Pause stops it. */
async function loadAndPlay(broadcast: Broadcast, match_id: number) {
  if (await broadcast.send({ command: 'load_match', match_id })) {
    await broadcast.send({ command: 'play' })
  }
}

const groupHeading = 'eyebrow w-20'

function ErrorMessage({ message }: { message: string | null }) {
  return (
    message && (
      <p role="alert" className="text-sm text-red-400">
        {message}
      </p>
    )
  )
}
