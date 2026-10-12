"""Run the pipeline against an event source and report on it."""

import asyncio
import logging
from collections.abc import Callable, Sequence

from engine.detectors import Detectors
from engine.hub import MatchHub
from engine.metrics import MetricsConfig, snapshot
from engine.pipeline import Pipeline
from engine.schema.engine_status_schema import EngineState, EngineStatus
from engine.schema.metric_schema import TeamMetrics
from engine.sinks import AlertSink
from engine.sources import EventSource
from engine.ticks import Ticker

log = logging.getLogger(__name__)


async def run(
    source: EventSource,
    pipeline: Pipeline,
    *,
    metrics: MetricsConfig | None = None,
    ticker: Ticker | None = None,
    detectors: Detectors | None = None,
    sinks: Sequence[AlertSink] = (),
    hub: MatchHub | None = None,
    status_every_s: float = 1.0,
    report: Callable[[str], None] = log.info,
) -> None:
    """Feed every message from source through pipeline until the source ends.

    On every tick the detectors, if given, run. The alerts they raise go to
    each sink, unless the tick is replayed: sinks only hear about live alerts.

    The hub, if given, gets everything: a reset whenever the pipeline starts
    over, then on every tick the metric snapshots and all alerts, replayed or
    not, so it holds the whole match.

    Every status_every_s seconds of wall-clock time, report the status (with
    metrics, if a config is given) if it has changed, and give it to the hub.
    """
    last = ""

    def report_if_changed() -> None:
        nonlocal last
        line = status_report(pipeline, metrics)
        if line != last:
            report(line)
            last = line
        if hub:
            hub.set_status(engine_status(pipeline))

    async def report_every() -> None:
        while True:
            await asyncio.sleep(status_every_s)
            report_if_changed()

    reporter = asyncio.create_task(report_every())
    try:
        async for msg in source.subscribe():
            items = pipeline.handle(msg)
            if hub and pipeline.generation != hub.generation:
                hub.start(pipeline.generation, pipeline.match_id)
                hub.set_status(engine_status(pipeline))
            for item in items:
                tick = ticker.observe(pipeline, item) if ticker else None
                if tick is None:
                    continue
                alerts = detectors.evaluate(tick) if detectors else []
                if hub:
                    hub.add(*tick.snapshots(), *alerts)
                if tick.replay:
                    continue
                for alert in alerts:
                    for sink in sinks:
                        sink.send(alert)
    finally:
        reporter.cancel()
        # Wait for it to finish. asyncio.wait never raises the reporter's own
        # CancelledError, but still lets a cancellation of run() through.
        await asyncio.wait([reporter])
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


def engine_status(p: Pipeline) -> EngineStatus:
    """Where the pipeline is in the match, for the dashboard."""
    if p.match_id is None:
        state = EngineState.waiting
    elif p.ended:
        state = EngineState.ended
    elif p.rebuilding:
        state = EngineState.rebuilding
    else:
        state = EngineState.live
    now, stats = p.clock.now, p.buffer.stats
    return EngineStatus(
        schema_version=1,
        state=state,
        generation=p.generation,
        match_id=p.match_id,
        teams=list(p.teams.values()) or None,
        period=now.period if now else None,
        match_clock_s=now.clock_s if now else None,
        play_s=p.clock.play_s if now else None,
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
