"""Command line: `uv run engine --help`."""

import argparse
import asyncio
import contextlib
import logging
import sys
from collections.abc import Sequence
from contextlib import AsyncExitStack
from pathlib import Path

from engine.detectors import ControlShift, Detectors, GoalThreat, Momentum
from engine.metrics import MetricsConfig, XTGrid, XTGridError
from engine.metrics.xt import DEFAULT_GRID_PATH
from engine.pipeline import Pipeline
from engine.runner import run
from engine.sinks import AlertSink, LogSink, WebhookSink
from engine.sources import WebSocketSource
from engine.ticks import Ticker
from engine.windows import InMemoryStateStore, WindowMode


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="engine",
        description="Read the simulator feed, compute live match metrics and raise alerts.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--feed", default="ws://localhost:8080/feed", help="simulator feed URL")
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
        "--webhook",
        action="append",
        default=[],
        metavar="URL",
        help="also POST each alert as JSON to URL (repeatable); alerts are always logged",
    )
    parser.add_argument(
        "--status-every", type=float, default=1.0, metavar="SECONDS", help="status line interval"
    )
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    args = parser.parse_args(argv)
    if args.allowed_lateness < 0:
        parser.error("--allowed-lateness must not be negative")
    if args.status_every <= 0:
        parser.error("--status-every must be positive")
    return args


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        grid = XTGrid.load(args.xt_grid)
    except XTGridError as e:
        sys.exit(f"engine: {e}")
    logging.basicConfig(
        level=args.log_level, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S"
    )
    # httpx logs every request at INFO; the webhook sink logs its own failures.
    logging.getLogger("httpx").setLevel(
        max(logging.WARNING, logging.getLevelNamesMapping()[args.log_level])
    )
    pipeline = Pipeline(
        InMemoryStateStore(),
        allowed_lateness_s=args.allowed_lateness,
        window_mode=args.window_mode,
    )
    metrics = MetricsConfig(grid)
    detectors = Detectors([Momentum(), GoalThreat(), ControlShift()])

    async def serve() -> None:
        async with AsyncExitStack() as stack:
            sinks: list[AlertSink] = [LogSink()]
            for url in args.webhook:
                sinks.append(await stack.enter_async_context(WebhookSink(url)))
            await run(
                WebSocketSource(args.feed),
                pipeline,
                metrics=metrics,
                ticker=Ticker(metrics),
                detectors=detectors,
                sinks=sinks,
                status_every_s=args.status_every,
            )

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve())
