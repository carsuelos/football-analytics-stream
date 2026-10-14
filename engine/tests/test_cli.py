import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest

from engine.cli import (
    SHUTDOWN_GRACE_S,
    Server,
    engine_app,
    event_source,
    feed_url,
    main,
    parse_args,
    server,
)
from engine.hub import MatchHub
from engine.metrics.xt import DEFAULT_GRID_PATH
from engine.schema.engine_status_schema import EngineState
from engine.schema.feed_schema import FeedMessage
from engine.sources import EventSource, KafkaSource, WebSocketSource
from engine.windows import WindowMode
from tests.test_api import serving, sse
from tests.test_hub import take
from tests.test_runner import METRICS, MSGS, ListSource


def test_cli_defaults_and_validation() -> None:
    args = parse_args([], env={})
    assert args.source == "ws"
    assert (args.kafka, args.alerts_topic, args.metrics_topic) == ({}, "alerts", "metrics")
    assert args.simulator == "http://localhost:8080"
    assert args.no_simulator is False
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
        ["--source", "kafka"],
        ["--source", "carrier-pigeon"],
        ["--no-simulator"],  # the ws feed is the simulator's
    ):
        with pytest.raises(SystemExit):
            parse_args(bad, env={})


def test_the_source_is_the_websocket_feed_or_a_kafka_topic() -> None:
    ws = event_source(parse_args([], env={}))
    assert isinstance(ws, WebSocketSource) and ws.url == "ws://localhost:8080/feed"

    env = {"KAFKA_BOOTSTRAP_SERVERS": "redpanda:9092", "KAFKA_CLIENT_ID": "engine-2"}
    kafka = event_source(parse_args(["--source", "kafka", "--kafka-topic", "feed"], env=env))
    assert isinstance(kafka, KafkaSource)
    assert kafka.config == {"bootstrap.servers": "redpanda:9092", "client.id": "engine-2"}
    assert kafka.topic == "feed"
    assert parse_args(["--source", "kafka", "--no-simulator"], env=env).no_simulator


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


def engine_server(
    source: EventSource, stops: list[BaseException | None], *, no_simulator: bool = False
) -> Server:
    """The engine on a free local port, reading source; run loop stops go to stops."""
    hub = MatchHub()
    args = parse_args(["--status-every", "0.01"], env={})
    args.no_simulator = no_simulator  # without Kafka settings, which would start a publisher
    app = engine_app(args, METRICS.grid, source, hub, stops.append)
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


async def test_without_a_simulator_the_engine_still_serves_the_match() -> None:
    stops: list[BaseException | None] = []
    async with (
        serving(engine_server(ListSource(*MSGS), stops, no_simulator=True)) as url,
        httpx.AsyncClient(base_url=url) as c,
    ):
        await until(lambda: stops)
        assert (await c.get("/api/status")).json()["released"] == 3
        assert (await c.get("/api/broadcast")).status_code == 404


async def test_viewer_controls_drive_the_engines_dvr() -> None:
    stops: list[BaseException | None] = []
    source = ListSource(*MSGS[:2], pause_s=0.2)
    async with (
        serving(engine_server(source, stops)) as url,
        httpx.AsyncClient(base_url=url) as c,
    ):
        pause = {"schema_version": 1, "command": "pause"}
        assert (await c.post("/api/control", json=pause)).status_code == 409  # no match yet
        await until(lambda: stops)
        r = await c.post("/api/control", json=pause)
        assert (r.status_code, r.json()["state"]) == (200, EngineState.paused)
        assert (await c.get("/api/status")).json()["state"] == EngineState.paused


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
