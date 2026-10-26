"""Run the pipeline against an event source and report on it."""

import asyncio
import logging
from collections.abc import Callable, Iterable, Sequence

from engine import telemetry
from engine.clock import TimedEvent
from engine.detectors import Detectors
from engine.dvr import Dvr
from engine.hub import MatchHub
from engine.incidents import IncidentTracker
from engine.metrics import MetricsConfig, snapshot
from engine.pipeline import Pipeline
from engine.schema.engine_status_schema import EngineState, EngineStatus
from engine.schema.feed_schema import FeedMessage
from engine.schema.metric_schema import TeamMetrics
from engine.sinks import AlertSink, MetricSink
from engine.sources import EventSource
from engine.ticks import Ticker

IDLE_RELEASE_S = 3.0
"""Wall-clock seconds without a message after which held events are let out."""

log = logging.getLogger(__name__)


async def run(
    source: EventSource,
    pipeline: Pipeline,
    *,
    metrics: MetricsConfig | None = None,
    ticker: Ticker | None = None,
    detectors: Detectors | None = None,
    incidents: IncidentTracker | None = None,
    sinks: Sequence[AlertSink] = (),
    metric_sinks: Sequence[MetricSink] = (),
    hub: MatchHub | None = None,
    status_every_s: float = 1.0,
    idle_release_s: float = IDLE_RELEASE_S,
    report: Callable[[str], None] = log.debug,
) -> None:
    """Feed every message from source through pipeline until the source ends.

    On every tick the detectors, if given, run. The alerts they raise go to
    each sink, and the tick's metric snapshots to each metric sink, unless the
    tick is replayed: sinks only hear about live ticks. A viewer re-watching
    part of the match makes those ticks live again, so sinks may get the same
    alert or snapshot twice; alert ids and snapshot (offset, window) tell them
    apart.

    The hub, if given, gets everything: a reset whenever the pipeline starts
    over, then the incidents (goals, cards...) as they happen, and on every
    tick the metric snapshots and all alerts, replayed or not, so it holds the
    whole match. The incident tracker, if given, also keeps the status's score.

    When no message has come for idle_release_s seconds of wall-clock time,
    the events the reorder buffer still holds are let out (Pipeline.release_idle):
    after a goal the feed can go quiet for minutes, and the goal shouldn't wait.

    At the start, then every status_every_s seconds of wall-clock time, report
    the status (with metrics, if a config is given; logged at DEBUG by default)
    if it has changed, and give it to the hub. If the source is a Dvr, the
    status includes the viewer's side.
    """
    last = ""
    dvr = source if isinstance(source, Dvr) else None

    def report_if_changed() -> None:
        nonlocal last
        line = status_report(pipeline, metrics)
        if line != last:
            report(line)
            last = line
        if hub:
            hub.set_status(engine_status(pipeline, dvr, incidents))

    async def report_every() -> None:
        while True:
            await asyncio.sleep(status_every_s)
            report_if_changed()

    def process(items: Iterable[TimedEvent]) -> None:
        for item in items:
            if incidents:
                found = incidents.observe(pipeline, item)
                if hub and found:
                    hub.add(*found)
            tick = ticker.observe(pipeline, item) if ticker else None
            if tick is None:
                continue
            alerts = detectors.evaluate(tick) if detectors else []
            snapshots = tick.snapshots() if hub or metric_sinks else []
            if hub:
                hub.add(*snapshots, *alerts)
            if tick.replay:
                continue
            for snap in snapshots:
                for metric_sink in metric_sinks:
                    metric_sink.send(snap)
            for alert in alerts:
                with telemetry.raising(alert, tick.item.event):
                    for sink in sinks:
                        sink.send(alert)

    # Messages come through a queue so the loop can notice the feed going
    # quiet (waiting on the queue can time out; on the source, it can't).
    queue: asyncio.Queue[FeedMessage | None] = asyncio.Queue(maxsize=1024)

    async def pump() -> None:
        try:
            async for msg in source.subscribe():
                await queue.put(msg)
        finally:
            await queue.put(None)

    report_if_changed()
    reporter = asyncio.create_task(report_every())
    reader = asyncio.create_task(pump())
    try:
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), idle_release_s)
            except TimeoutError:
                # Quiet for a while: let out what the reorder buffer holds.
                process(pipeline.release_idle())
                continue
            if msg is None:
                break
            items = pipeline.handle_each(msg)
            if hub and pipeline.generation != hub.generation:
                hub.start(pipeline.generation, pipeline.match_id)
                hub.set_status(engine_status(pipeline, dvr, incidents))
            process(items)
        if reader.done() and (error := reader.exception()) is not None:
            raise error
    finally:
        reporter.cancel()
        reader.cancel()
        # Wait for them to finish. asyncio.wait never raises their own
        # CancelledError, but still lets a cancellation of run() through.
        await asyncio.wait([reporter, reader])
    report_if_changed()


def status_report(p: Pipeline, metrics: MetricsConfig | None = None) -> str:
    """Where the match is and what the pipeline holds, then one line per window
    with each team's metrics if a config is given and both teams have appeared."""
    if p.windows is None or p.clock.now is None:
        return f"match {p.match_id}: waiting for events" if p.match_id else "waiting for a match"
    s = p.buffer.stats
    parts = [
        f"match {p.match_id} {p.clock.now} (play {_mmss(p.clock.play_s)})",
        f"released {s.released} buffered {len(p.buffer)} late {s.late_dropped} dup {s.duplicates}",
    ]
    if p.rebuilding:
        parts.append(f"rebuilding to offset {p.replay_end_offset}")
    if p.ended:
        parts.append("ended")
    lines = [" | ".join(parts)]
    if metrics and p.team_ids:
        for length_s in p.windows.lengths_s:
            snap = snapshot(p.windows, length_s, p.team_ids, metrics)
            if snap:
                teams = " | ".join(_team_metrics(p.teams[m.team_id].name, m) for m in snap.teams)
                lines.append(f"  last {length_s / 60:g}': {teams}")
    return "\n".join(lines)


def engine_status(
    p: Pipeline, dvr: Dvr | None = None, incidents: IncidentTracker | None = None
) -> EngineStatus:
    """Where the pipeline is in the match, the score if there is an incident
    tracker, and the viewer relative to the broadcast if there is a DVR, for
    the dashboard."""
    if p.match_id is None:
        state = EngineState.waiting
    elif p.ended:
        state = EngineState.ended
    elif p.rebuilding:
        state = EngineState.rebuilding
    elif dvr:
        state = EngineState(dvr.mode)
    else:
        state = EngineState.live
    now, stats = p.clock.now, p.buffer.stats
    return EngineStatus(
        schema_version=1,
        state=state,
        speed=dvr.speed if dvr else None,
        live_edge=dvr.live_edge() if dvr else None,
        behind_live_s=dvr.behind_live_s() if dvr else None,
        generation=p.generation,
        match_id=p.match_id,
        teams=list(p.teams.values()) or None,
        score=incidents.score(p) if incidents else None,
        period=now.period if now else None,
        match_clock_s=now.clock_s if now else None,
        play_s=p.clock.play_s if now else None,
        period_over=p.clock.period_over if now else None,
        rebuilding_to=p.replay_end_offset if p.rebuilding else None,
        released=stats.released,
        buffered=len(p.buffer),
        late_dropped=stats.late_dropped,
        duplicates=stats.duplicates,
    )


def _team_metrics(name: str, m: TeamMetrics) -> str:
    return (
        f"{name} tilt {m.field_tilt:.0%} xT {m.xt_added:+.2f} ({m.xt_velocity:+.3f}/min)"
        f" pressure {m.pressure_index:.1f}"
    )


def _mmss(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"
