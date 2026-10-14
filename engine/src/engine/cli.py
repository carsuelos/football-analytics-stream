"""Command line: `uv run engine --help`."""

import argparse
import asyncio
import contextlib
import logging
import os
import socket
import sys
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
import uvicorn
from fastapi import FastAPI

from engine.api import create_app
from engine.detectors import GoalModel, GoalModelError, default_detectors
from engine.detectors.goal_chance import add_goal_model_args, grid_mismatch
from engine.dvr import Dvr
from engine.hub import MatchHub
from engine.incidents import IncidentTracker
from engine.metrics import MetricsConfig, XTGrid, XTGridError
from engine.metrics.xt import DEFAULT_GRID_PATH
from engine.pipeline import Pipeline
from engine.runner import engine_status, run
from engine.schema.engine_status_schema import EngineStatus
from engine.schema.viewer_command_schema import ViewerCommand
from engine.sinks import (
    AlertSink,
    KafkaAlertSink,
    KafkaMetricSink,
    KafkaPublisher,
    LogSink,
    MetricSink,
    WebhookSink,
)
from engine.sources import EventSource, KafkaSource, WebSocketSource
from engine.sources.kafka import config_from_env
from engine.ticks import TICK_S, Ticker
from engine.windows import InMemoryStateStore, WindowMode

log = logging.getLogger(__name__)

# Seconds to let open requests finish on shutdown before cancelling them. The
# server ends the streams itself (see Server), so this is only a backstop.
SHUTDOWN_GRACE_S = 1


def parse_args(
    argv: Sequence[str] | None = None, env: Mapping[str, str] = os.environ
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="engine",
        description="Read the simulator feed, compute live match metrics and raise alerts, "
        "and serve them to the dashboard.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--simulator",
        default="http://localhost:8080",
        metavar="URL",
        help="simulator base URL: broadcast controls pass through to it, and with --source ws "
        "the feed is its /feed",
    )
    parser.add_argument(
        "--no-simulator",
        action="store_true",
        help="there is no simulator to control (as with a real feed): the broadcast endpoints "
        "answer 404 and the dashboard hides its simulator controls; needs --source kafka",
    )
    parser.add_argument(
        "--source",
        choices=["ws", "kafka"],
        default="ws",
        help="read the broadcast from the simulator's WebSocket feed, or from the Kafka topic it "
        "publishes to (set KAFKA_BOOTSTRAP_SERVERS, and any other KAFKA_* client settings)",
    )
    parser.add_argument(
        "--kafka-topic", default="events", metavar="TOPIC", help="the topic for --source kafka"
    )
    parser.add_argument(
        "--alerts-topic",
        default="alerts",
        metavar="TOPIC",
        help="with KAFKA_BOOTSTRAP_SERVERS set, publish live alerts to this topic",
    )
    parser.add_argument(
        "--metrics-topic",
        default="metrics",
        metavar="TOPIC",
        help="with KAFKA_BOOTSTRAP_SERVERS set, publish live metric snapshots to this topic",
    )
    parser.add_argument("--host", default="127.0.0.1", help="address to serve the API on")
    parser.add_argument("--port", type=int, default=8000, help="port to serve the API on")
    parser.add_argument(
        "--allowed-lateness",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="how late (in match seconds) an event may arrive and still be used",
    )
    parser.add_argument(
        "--window-mode",
        type=WindowMode,
        choices=list(WindowMode),
        default=WindowMode.CONTINUOUS,
        help="continuous: windows run across half-time; per_period: they restart at kick-off",
    )
    parser.add_argument(
        "--xt-grid",
        type=Path,
        default=DEFAULT_GRID_PATH,
        metavar="PATH",
        help="12x8 expected-threat grid JSON (downloaded by make fetch-data)",
    )
    parser.add_argument(
        "--tick",
        type=float,
        default=TICK_S,
        metavar="SECONDS",
        help="how often (in seconds of play) to snapshot the metrics and run the detectors",
    )
    add_goal_model_args(parser)
    parser.add_argument(
        "--webhook",
        action="append",
        default=[],
        metavar="URL",
        help="also POST each alert as JSON to URL (repeatable); alerts are always logged",
    )
    parser.add_argument(
        "--status-every",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="how often to refresh the engine status (logged at DEBUG)",
    )
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    args = parser.parse_args(argv)
    try:
        args.feed = feed_url(args.simulator)
    except ValueError as e:
        parser.error(f"--simulator: {e}")
    args.kafka = config_from_env(env)
    if args.source == "kafka" and "bootstrap.servers" not in args.kafka:
        parser.error("--source kafka needs KAFKA_BOOTSTRAP_SERVERS")
    if args.no_simulator and args.source != "kafka":
        parser.error("--no-simulator needs --source kafka: the ws feed is the simulator's")
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if args.allowed_lateness < 0:
        parser.error("--allowed-lateness must not be negative")
    if args.tick <= 0:
        parser.error("--tick must be positive")
    if args.status_every <= 0:
        parser.error("--status-every must be positive")
    return args


def feed_url(simulator: str) -> str:
    """The simulator's WebSocket feed: http://host:port -> ws://host:port/feed."""
    url = urlsplit(simulator)
    schemes = {"http": "ws", "https": "wss"}
    if url.scheme not in schemes or not url.netloc:
        raise ValueError(f"want an http:// or https:// URL, got {simulator!r}")
    return urlunsplit((schemes[url.scheme], url.netloc, url.path.rstrip("/") + "/feed", "", ""))


def event_source(args: argparse.Namespace) -> EventSource:
    if args.source == "kafka":
        return KafkaSource(args.kafka, args.kafka_topic)
    return WebSocketSource(args.feed)


def engine_app(
    args: argparse.Namespace,
    grid: XTGrid,
    source: EventSource,
    hub: MatchHub,
    on_stop: Callable[[BaseException | None], None],
    goal_model: GoalModel | None = None,
) -> FastAPI:
    """The API over hub, with the run loop filling hub while the app is up.

    The source goes through a DVR, which the API's viewer controls drive.

    The source never ends on its own (it reconnects), so if the run loop stops
    while the app is up, something is wrong: it is logged and on_stop is called
    with the error (None if the source just ended) so the server can exit.
    """
    pipeline = Pipeline(
        InMemoryStateStore(),
        allowed_lateness_s=args.allowed_lateness,
        window_mode=args.window_mode,
    )
    metrics = MetricsConfig(grid)
    simulator = None if args.no_simulator else httpx.AsyncClient(base_url=args.simulator, timeout=5)
    dvr = Dvr(source)
    incidents = IncidentTracker()

    def control(cmd: ViewerCommand) -> EngineStatus:
        dvr.execute(cmd)
        status = engine_status(pipeline, dvr, incidents)
        hub.set_status(status)
        return status

    def stopped(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        log.error("run loop stopped", exc_info=error)
        on_stop(error)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            if simulator is not None:
                await stack.enter_async_context(simulator)
            sinks: list[AlertSink] = [LogSink()]
            metric_sinks: list[MetricSink] = []
            for url in args.webhook:
                sinks.append(await stack.enter_async_context(WebhookSink(url)))
            if "bootstrap.servers" in args.kafka:
                publisher = await stack.enter_async_context(KafkaPublisher(args.kafka))
                sinks.append(KafkaAlertSink(publisher, args.alerts_topic))
                metric_sinks.append(KafkaMetricSink(publisher, args.metrics_topic))
            loop = asyncio.create_task(
                run(
                    dvr,
                    pipeline,
                    metrics=metrics,
                    ticker=Ticker(metrics, args.tick),
                    detectors=default_detectors(goal_model),
                    incidents=incidents,
                    sinks=sinks,
                    metric_sinks=metric_sinks,
                    hub=hub,
                    status_every_s=args.status_every,
                )
            )
            loop.add_done_callback(stopped)
            try:
                yield
            finally:
                loop.cancel()
                await asyncio.wait([loop])

    return create_app(hub, simulator, control=control, lifespan=lifespan)


class Server(uvicorn.Server):
    """uvicorn's server, but it closes the hub as it starts shutting down.

    uvicorn waits for open requests to finish before it stops, and a stream
    never finishes by itself. Closing the hub ends every stream, so they finish
    cleanly instead of being cancelled when the grace period runs out.
    """

    def __init__(self, config: uvicorn.Config, hub: MatchHub) -> None:
        super().__init__(config)
        self.hub = hub

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        self.hub.close()
        await super().shutdown(sockets)


def server(app: FastAPI, hub: MatchHub, host: str, port: int) -> Server:
    """A server for app (whose streams come from hub) that logs through the root logger."""
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_config=None,  # keep our logging setup and format
        timeout_graceful_shutdown=SHUTDOWN_GRACE_S,
    )
    return Server(config, hub)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        grid = XTGrid.load(args.xt_grid)
        goal_model = GoalModel.load(args.goal_model) if args.goal_model else None
    except (XTGridError, GoalModelError) as e:
        sys.exit(f"engine: {e}")
    logging.basicConfig(
        level=args.log_level, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S"
    )
    # httpx logs every request at INFO; the webhook sink logs its own failures.
    logging.getLogger("httpx").setLevel(
        max(logging.WARNING, logging.getLevelNamesMapping()[args.log_level])
    )
    if goal_model and (warning := grid_mismatch(goal_model, args.xt_grid)):
        log.warning("%s", warning)
    failed = False

    def stop(_: BaseException | None) -> None:
        nonlocal failed
        failed = True
        srv.should_exit = True

    hub = MatchHub()
    app = engine_app(args, grid, event_source(args), hub, on_stop=stop, goal_model=goal_model)
    srv = server(app, hub, args.host, args.port)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(srv.serve())
    if failed:
        sys.exit("engine: the run loop stopped; see the log above")
