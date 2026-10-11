"""Run the pipeline against an event source and report on it."""

import asyncio
import logging
from collections import Counter
from collections.abc import Callable

from engine.pipeline import Pipeline
from engine.sources import EventSource

log = logging.getLogger(__name__)


async def run(
    source: EventSource,
    pipeline: Pipeline,
    *,
    status_every_s: float = 1.0,
    report: Callable[[str], None] = log.info,
) -> None:
    """Feed every message from source through pipeline until the source ends.

    Every status_every_s seconds of wall-clock time, report the status line if
    it has changed.
    """
    last = ""

    def report_if_changed() -> None:
        nonlocal last
        line = status_line(pipeline)
        if line != last:
            report(line)
            last = line

    async def tick() -> None:
        while True:
            await asyncio.sleep(status_every_s)
            report_if_changed()

    ticker = asyncio.create_task(tick())
    try:
        async for msg in source.subscribe():
            pipeline.handle(msg)
    finally:
        ticker.cancel()
        # Wait for it to finish. asyncio.wait never raises the ticker's own
        # CancelledError, but still lets a cancellation of run() through.
        await asyncio.wait([ticker])
    report_if_changed()


def status_line(p: Pipeline) -> str:
    """One line on where the match is and what the pipeline holds."""
    if p.windows is None or p.clock.now is None:
        return f"match {p.match_id}: waiting for events" if p.match_id else "waiting for a match"
    s = p.buffer.stats
    parts = [
        f"match {p.match_id} {p.clock.now} (play {_mmss(p.clock.play_s)})",
        f"released {s.released} buffered {len(p.buffer)} late {s.late_dropped} dup {s.duplicates}",
    ]
    for length_s in p.windows.lengths_s:
        teams = Counter(i.event.team.name for i in p.windows.events(length_s))
        counts = ", ".join(f"{name} {n}" for name, n in sorted(teams.items())) or "-"
        parts.append(f"last {length_s / 60:g}': {counts}")
    if p.rebuilding:
        parts.append(f"rebuilding to offset {p.replay_end_offset}")
    if p.ended:
        parts.append("ended")
    return " | ".join(parts)


def _mmss(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"
