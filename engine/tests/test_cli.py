import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest

from engine.cli import SHUTDOWN_GRACE_S, Server, engine_app, feed_url, main, parse_args, server
from engine.hub import MatchHub
from engine.metrics.xt import DEFAULT_GRID_PATH
from engine.schema.engine_status_schema import EngineState
from engine.schema.feed_schema import FeedMessage
from engine.sources import EventSource
from engine.windows import WindowMode
from tests.test_api import serving, sse
from tests.test_hub import take
from tests.test_runner import METRICS, MSGS, ListSource


def test_cli_defaults_and_validation() -> None:
    args = parse_args([])
    assert args.simulator == "http://localhost:8080"
    assert args.feed == "ws://localhost:8080/feed"
    assert (args.host, args.port) == ("127.0.0.1", 8000)
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
    for bad in (
        ["--allowed-lateness", "-1"],
        ["--window-mode", "sideways"],
        ["--simulator", "ws://localhost:8080"],
        ["--simulator", "localhost:8080"],
        ["--simulator", "http://"],
        ["--port", "70000"],
        ["--status-every", "0"],
    ):
        with pytest.raises(SystemExit):
            parse_args(bad)


@pytest.mark.parametrize(
    ("simulator", "feed"),
    [
        ("http://localhost:8080", "ws://localhost:8080/feed"),
        ("https://sim.example.com/", "wss://sim.example.com/feed"),
        ("http://proxy:9000/simulator/", "ws://proxy:9000/simulator/feed"),
    ],
)
def test_the_feed_is_the_simulators_websocket(simulator: str, feed: str) -> None:
    assert feed_url(simulator) == feed


def test_cli_exits_with_a_hint_when_the_xt_grid_is_missing(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="make fetch-data"):
        main(["--xt-grid", str(tmp_path / "missing.json")])


class Failing:
    """An EventSource that sends the start of a match, then fails."""

    async def subscribe(self, from_offset: int = 0) -> AsyncIterator[FeedMessage]:
        yield MSGS[0]
        raise ConnectionError("boom")


def engine_server(source: EventSource, stops: list[BaseException | None]) -> Server:
    """The engine on a free local port, reading source; run loop stops go to stops."""
    hub = MatchHub()
    app = engine_app(
        parse_args(["--status-every", "0.01"]), METRICS.grid, source, hub, stops.append
    )
    return server(app, hub, "127.0.0.1", 0)


async def until(condition: Callable[[], object], timeout_s: float = 2) -> None:
    async with asyncio.timeout(timeout_s):
        while not condition():
            await asyncio.sleep(0.01)


async def test_the_engine_serves_the_match_its_run_loop_builds() -> None:
    stops: list[BaseException | None] = []
    async with (
        serving(engine_server(ListSource(*MSGS), stops)) as url,
        httpx.AsyncClient(base_url=url) as c,
    ):
        await until(lambda: stops)
        status = (await c.get("/api/status")).json()
        metrics = (await c.get("/api/metrics")).json()
    assert (status["state"], status["released"]) == (EngineState.ended, 3)
    assert len(metrics) == 4
    # The test source simply ends; a real one never does, so the engine stops.
    assert stops == [None]


async def test_a_failing_run_loop_stops_the_engine(caplog: pytest.LogCaptureFixture) -> None:
    stops: list[BaseException | None] = []
    async with serving(engine_server(Failing(), stops)):
        await until(lambda: stops)
    [error] = stops
    assert isinstance(error, ConnectionError)
    assert "run loop stopped" in caplog.text


async def test_shutdown_ends_open_streams_cleanly(caplog: pytest.LogCaptureFixture) -> None:
    stops: list[BaseException | None] = []
    loop = asyncio.get_running_loop()
    async with httpx.AsyncClient() as client:
        async with serving(engine_server(ListSource(*MSGS, pause_s=60), stops)) as url:
            r = await client.send(client.build_request("GET", f"{url}/api/stream"), stream=True)
            # Keep a reference: a dropped generator closes the connection when
            # garbage collected, and then there would be no open stream.
            events = sse(r)
            await take(events, 1)
            started = loop.time()
        # serving has stopped the server with the stream still open: it ended
        # the stream rather than waiting out the grace period and cancelling it.
        assert loop.time() - started < SHUTDOWN_GRACE_S
        await events.aclose()
        await r.aclose()
    assert stops == []  # the run loop was cancelled, not stopped
    assert [r.message for r in caplog.records if r.levelno >= logging.ERROR] == []
