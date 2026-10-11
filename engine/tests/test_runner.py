import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from engine.cli import main, parse_args
from engine.metrics import MetricsConfig, XTGrid
from engine.metrics.xt import DEFAULT_GRID_PATH
from engine.pipeline import Pipeline
from engine.runner import run, status_report
from engine.schema.feed_schema import FeedMessage
from engine.schema.feed_schema import FeedMessageKind as K
from engine.windows import InMemoryStateStore, WindowMode
from tests.factories import AWAY, HOME, event, feed_event, feed_marker


class ListSource:
    """An EventSource that plays a fixed list of messages, then ends."""

    def __init__(self, *msgs: FeedMessage, pause_s: float = 0) -> None:
        self.msgs = msgs
        self.pause_s = pause_s

    async def subscribe(self, from_offset: int = 0) -> AsyncIterator[FeedMessage]:
        for msg in self.msgs:
            await asyncio.sleep(self.pause_s)
            yield msg


MSGS = (
    feed_marker(K.match_start, 0),
    feed_event(event(1, 0, offset=0, team=HOME)),
    feed_event(event(1, 70, offset=1, team=AWAY)),
    feed_event(event(1, 400, offset=2, team=HOME)),
    feed_marker(K.match_end, 3),
)


METRICS = MetricsConfig(XTGrid.from_lists([[0.0] * 12] * 8))


def test_status_report_before_and_during_a_match() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    assert status_report(p, METRICS) == "waiting for a match"
    p.handle(MSGS[0])
    assert status_report(p, METRICS) == "match 1: waiting for events"
    for msg in MSGS[1:]:
        p.handle(msg)
    header = "match 1 P1 06:40 (play 06:40) | released 3 buffered 0 late 0 dup 0 | ended"
    assert status_report(p) == header
    assert status_report(p, METRICS).splitlines() == [
        header,
        "  last 5': Home FC tilt 50% xT +0.00 (+0.000/min) pressure 0.0"
        " | Away FC tilt 50% xT +0.00 (+0.000/min) pressure 0.0",
        "  last 10': Home FC tilt 50% xT +0.00 (+0.000/min) pressure 0.0"
        " | Away FC tilt 50% xT +0.00 (+0.000/min) pressure 0.0",
    ]


def test_status_report_has_no_metrics_until_both_teams_appear() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    for msg in MSGS[:2]:
        p.handle(msg)
    p.handle(feed_marker(K.match_end, 1))
    assert len(status_report(p, METRICS).splitlines()) == 1


def test_status_report_shows_rebuilding_after_a_seek() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    for msg in (*MSGS[:4], feed_marker(K.reset, 3), MSGS[1]):
        p.handle(msg)
    assert status_report(p).endswith("| rebuilding to offset 3")


async def test_run_reports_status_while_running_and_at_the_end() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    lines: list[str] = []
    source = ListSource(*MSGS, pause_s=0.02)
    await run(source, p, metrics=METRICS, status_every_s=0.01, report=lines.append)
    assert lines[0] == "waiting for a match"
    assert lines[-1].splitlines()[0].endswith("| ended")
    assert "pressure" in lines[-1]
    assert len(lines) == len(set(lines))  # unchanged lines are not repeated


async def test_run_stops_the_status_ticker_when_the_source_fails() -> None:
    class Broken:
        async def subscribe(self, from_offset: int = 0) -> AsyncIterator[FeedMessage]:
            yield MSGS[0]
            raise ConnectionError("boom")

    with pytest.raises(ConnectionError):
        await run(Broken(), Pipeline(InMemoryStateStore()), report=lambda _: None)
    assert [t for t in asyncio.all_tasks() if t is not asyncio.current_task()] == []


def test_cli_defaults_and_validation() -> None:
    args = parse_args([])
    assert args.feed == "ws://localhost:8080/feed"
    assert args.allowed_lateness == 5.0
    assert args.window_mode is WindowMode.CONTINUOUS
    assert args.xt_grid == DEFAULT_GRID_PATH
    assert parse_args(["--window-mode", "per_period"]).window_mode is WindowMode.PER_PERIOD
    assert parse_args(["--xt-grid", "g.json"]).xt_grid == Path("g.json")
    with pytest.raises(SystemExit):
        parse_args(["--allowed-lateness", "-1"])
    with pytest.raises(SystemExit):
        parse_args(["--window-mode", "sideways"])


def test_cli_exits_with_a_hint_when_the_xt_grid_is_missing(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="make fetch-data"):
        main(["--xt-grid", str(tmp_path / "missing.json")])
