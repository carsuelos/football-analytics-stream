import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from engine.cli import main, parse_args
from engine.detectors import Detectors
from engine.metrics import MetricsConfig, XTGrid
from engine.metrics.xt import DEFAULT_GRID_PATH
from engine.pipeline import Pipeline
from engine.runner import run, status_report
from engine.schema.alert_schema import Alert
from engine.schema.feed_schema import FeedMessage
from engine.schema.feed_schema import FeedMessageKind as K
from engine.ticks import Ticker
from engine.windows import InMemoryStateStore, WindowMode
from tests.factories import AWAY, HOME, event, feed_event, feed_marker
from tests.test_detectors import Fake


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


class ListSink(list[Alert]):
    def send(self, alert: Alert) -> None:
        self.append(alert)


async def test_run_sends_every_alert_to_every_sink() -> None:
    sinks = ListSink(), ListSink()
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    await run(
        ListSource(*MSGS),
        p,
        ticker=Ticker(METRICS),
        detectors=Detectors([Fake()]),
        sinks=sinks,
        report=lambda _: None,
    )
    # Ticks at 01:10 (the first with both teams) and 06:40, past the cooldown.
    assert [(a.offset, a.team_id) for a in sinks[0]] == [(1, HOME.id), (2, HOME.id)]
    assert sinks[1] == sinks[0]


async def test_run_sends_only_live_alerts_to_the_sinks() -> None:
    sink = ListSink()
    catch_up = (feed_marker(K.match_start, 0, head=2), *MSGS[1:])
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    await run(
        ListSource(*catch_up),
        p,
        ticker=Ticker(METRICS),
        detectors=Detectors([Fake()]),
        sinks=[sink],
        report=lambda _: None,
    )
    # The alert at 01:10 was caught up on; only the one at 06:40 is live.
    assert [a.offset for a in sink] == [2]


async def test_run_ticks_without_detectors() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    await run(ListSource(*MSGS), p, ticker=Ticker(METRICS), report=lambda _: None)
    assert p.clock.now is not None


async def test_run_stops_the_status_reporter_when_the_source_fails() -> None:
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
    assert args.webhook == []
    assert parse_args(["--webhook", "http://a", "--webhook", "http://b"]).webhook == [
        "http://a",
        "http://b",
    ]
    assert parse_args(["--window-mode", "per_period"]).window_mode is WindowMode.PER_PERIOD
    assert parse_args(["--xt-grid", "g.json"]).xt_grid == Path("g.json")
    with pytest.raises(SystemExit):
        parse_args(["--allowed-lateness", "-1"])
    with pytest.raises(SystemExit):
        parse_args(["--window-mode", "sideways"])


def test_cli_exits_with_a_hint_when_the_xt_grid_is_missing(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="make fetch-data"):
        main(["--xt-grid", str(tmp_path / "missing.json")])
