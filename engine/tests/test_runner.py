import asyncio
from collections.abc import AsyncIterator

import pytest

from engine.cli import parse_args
from engine.pipeline import Pipeline
from engine.runner import run, status_line
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


def test_status_line_before_and_during_a_match() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    assert status_line(p) == "waiting for a match"
    p.handle(MSGS[0])
    assert status_line(p) == "match 1: waiting for events"
    for msg in MSGS[1:]:
        p.handle(msg)
    assert status_line(p) == (
        "match 1 P1 06:40 (play 06:40) | released 3 buffered 0 late 0 dup 0"
        " | last 5': Home FC 1 | last 10': Away FC 1, Home FC 2 | ended"
    )


def test_status_line_shows_rebuilding_after_a_seek() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    for msg in (*MSGS[:4], feed_marker(K.reset, 3), MSGS[1]):
        p.handle(msg)
    assert status_line(p).endswith("| rebuilding to offset 3")


async def test_run_reports_status_while_running_and_at_the_end() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    lines: list[str] = []
    await run(ListSource(*MSGS, pause_s=0.02), p, status_every_s=0.01, report=lines.append)
    assert lines[0] == "waiting for a match"
    assert lines[-1].endswith("| ended")
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
    assert parse_args(["--window-mode", "per_period"]).window_mode is WindowMode.PER_PERIOD
    with pytest.raises(SystemExit):
        parse_args(["--allowed-lateness", "-1"])
    with pytest.raises(SystemExit):
        parse_args(["--window-mode", "sideways"])
