"""Command line: `uv run engine --help`."""

import argparse
import asyncio
import contextlib
import logging
from collections.abc import Sequence

from engine.pipeline import Pipeline
from engine.runner import run
from engine.sources import WebSocketSource
from engine.windows import InMemoryStateStore, WindowMode


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="engine",
        description="Read the simulator feed and keep live windows of match events.",
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
    logging.basicConfig(
        level=args.log_level, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S"
    )
    pipeline = Pipeline(
        InMemoryStateStore(),
        allowed_lateness_s=args.allowed_lateness,
        window_mode=args.window_mode,
    )
    source = WebSocketSource(args.feed)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(source, pipeline, status_every_s=args.status_every))
