"""Offline replay: run exported feeds through the engine, with no network or clock.

    make export                                           # the simulator writes data/feeds
    uv run python -m engine.backtest ../data/feeds        # every exported match
    uv run python -m engine.backtest ../data/feeds/3869685.jsonl

A feed file holds what the simulator broadcasts for one match (see the
simulator's cmd/export). Replaying it here runs the same pipeline, ticker and
detectors as the live engine, message by message, so the metrics and alerts are
exactly the ones the engine raises live, only as fast as the CPU allows: a
whole tournament takes seconds, not hours. Backtests, the evaluation of the
alerts and the model's training data all come from here.
"""

import argparse
import json
import os
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from engine.clock import TimedEvent
from engine.detectors import ControlShift, Detectors, GoalThreat, Momentum
from engine.metrics import MetricsConfig, XTGrid
from engine.metrics.xt import DEFAULT_GRID_PATH
from engine.pipeline import Pipeline
from engine.schema.alert_schema import Alert
from engine.schema.event_schema import EventType, MatchEvent, ShotOutcome
from engine.schema.feed_schema import FeedMessage
from engine.schema.metric_schema import MetricSnapshot
from engine.ticks import SHOOTOUT_PERIOD, Tick, Ticker
from engine.windows import InMemoryStateStore


def read_feed(path: Path) -> Iterator[FeedMessage]:
    """The messages in a feed file, one JSON message per line."""
    with path.open() as f:
        for line in f:
            if line.strip():
                yield FeedMessage.model_validate_json(line)


def feed_paths(paths: Iterable[Path]) -> list[Path]:
    """The feed files named, with each directory standing for the feeds in it."""
    found: list[Path] = []
    for path in paths:
        found += sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    return found


@dataclass(frozen=True)
class Step:
    """One event released by the pipeline, and the tick it makes, if it does.

    The tick is a view of the pipeline (see Tick): use it before taking the
    next step.
    """

    item: TimedEvent
    tick: Tick | None


def steps(messages: Iterable[FeedMessage], pipeline: Pipeline, ticker: Ticker) -> Iterator[Step]:
    """Feed messages through pipeline, as the live engine does (see runner.run)."""
    for msg in messages:
        for item in pipeline.handle(msg):
            yield Step(item, ticker.observe(pipeline, item))


def goal_for(event: MatchEvent, team_ids: tuple[int, int] | None) -> int | None:
    """The team a goal counts for, if the event is one. An own goal's team is
    the side that conceded it. Shootout kicks are not goals."""
    if event.period == SHOOTOUT_PERIOD:
        return None
    if event.type == EventType.shot and event.shot and event.shot.outcome == ShotOutcome.goal:
        return event.team.id
    if event.type == EventType.own_goal and team_ids:
        a, b = team_ids
        return b if event.team.id == a else a
    return None


@dataclass(frozen=True)
class Goal:
    team_id: int
    """The team the goal counts for."""
    play_s: float
    offset: int
    own_goal: bool


@dataclass(frozen=True)
class TimedAlert:
    alert: Alert
    play_s: float


@dataclass
class Replay:
    """What the engine made of one match."""

    match_id: int
    team_ids: tuple[int, int]
    team_names: dict[int, str]
    snapshots: list[MetricSnapshot] = field(default_factory=list)
    alerts: list[TimedAlert] = field(default_factory=list)
    goals: list[Goal] = field(default_factory=list)
    """Goals among the released events, not counting the shootout."""
    end_play_s: float = 0.0
    """Play time of the last event released before any shootout."""
    ended: bool = False
    released: int = 0
    late_dropped: int = 0
    duplicates: int = 0


def default_detectors() -> Detectors:
    """The live engine's detectors (see cli)."""
    return Detectors([Momentum(), GoalThreat(), ControlShift()])


def replay(
    messages: Iterable[FeedMessage],
    metrics: MetricsConfig,
    *,
    detectors: Detectors | None = None,
    snapshots: bool = False,
    on_step: Callable[[Pipeline, Step], None] | None = None,
) -> Replay:
    """Replay one match's feed through a fresh pipeline.

    Alerts come from detectors (none if not given); snapshots says whether to
    keep every tick's metric snapshots, which the evaluation does not need.
    on_step, if given, sees every step, e.g. to compute features.
    """
    pipeline = Pipeline(InMemoryStateStore())
    ticker = Ticker(metrics)
    result: Replay | None = None
    for step in steps(messages, pipeline, ticker):
        if result is None:
            result = Replay(step.item.event.match_id, (0, 0), {})
        if (team := goal_for(step.item.event, pipeline.team_ids)) is not None:
            ev = step.item.event
            result.goals.append(
                Goal(team, step.item.play_s, ev.offset, ev.type == EventType.own_goal)
            )
        if step.item.event.period != SHOOTOUT_PERIOD:
            result.end_play_s = step.item.play_s
        if step.tick is not None:
            if detectors:
                result.alerts += [
                    TimedAlert(a, step.tick.play_s) for a in detectors.evaluate(step.tick)
                ]
            if snapshots:
                result.snapshots += step.tick.snapshots()
        if on_step:
            on_step(pipeline, step)
    if result is None or pipeline.team_ids is None:
        raise ValueError("the feed has no events from both teams")
    result.team_ids = pipeline.team_ids
    result.team_names = {id: team.name for id, team in pipeline.teams.items()}
    result.ended = pipeline.ended
    stats = pipeline.buffer.stats
    result.released, result.late_dropped = stats.released, stats.late_dropped
    result.duplicates = stats.duplicates
    return result


def replay_file(path: Path, grid_path: Path = DEFAULT_GRID_PATH, snapshots: bool = False) -> Replay:
    """Replay a feed file with the live engine's detectors."""
    metrics = MetricsConfig(XTGrid.load(grid_path))
    return replay(read_feed(path), metrics, detectors=default_detectors(), snapshots=snapshots)


def replay_files(
    paths: Sequence[Path],
    grid_path: Path = DEFAULT_GRID_PATH,
    snapshots: bool = False,
    workers: int | None = None,
) -> Iterator[Replay]:
    """Replay many feed files in parallel, yielding results in the given order."""
    workers = workers or os.cpu_count() or 1
    if workers == 1 or len(paths) <= 1:
        for path in paths:
            yield replay_file(path, grid_path, snapshots)
        return
    with ProcessPoolExecutor(max_workers=min(workers, len(paths))) as pool:
        yield from pool.map(
            replay_file,
            paths,
            [grid_path] * len(paths),
            [snapshots] * len(paths),
        )


def summary(r: Replay) -> dict[str, object]:
    """One line of JSON about a replay, for the command line."""
    goals: dict[int, int] = dict.fromkeys(r.team_ids, 0)
    for g in r.goals:
        goals[g.team_id] += 1
    alerts: dict[str, int] = {}
    for a in r.alerts:
        alerts[a.alert.type] = alerts.get(a.alert.type, 0) + 1
    return {
        "match_id": r.match_id,
        "teams": [r.team_names[t] for t in r.team_ids],
        "score": [goals[t] for t in r.team_ids],
        "alerts": alerts,
        "end_play_min": round(r.end_play_s / 60, 1),
        "released": r.released,
        "late_dropped": r.late_dropped,
        "duplicates": r.duplicates,
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m engine.backtest",
        description="Replay exported feeds (make export) through the engine offline and print "
        "one JSON line per match: the score, the alerts by type and the feed's stats.",
    )
    parser.add_argument(
        "paths", nargs="+", type=Path, metavar="PATH", help="feed files or directories of them"
    )
    parser.add_argument("--xt-grid", type=Path, default=DEFAULT_GRID_PATH, metavar="PATH")
    parser.add_argument(
        "--workers", type=int, default=None, help="processes (default: one per CPU)"
    )
    args = parser.parse_args(argv)
    paths = feed_paths(args.paths)
    if not paths:
        parser.error("no feed files found (run make export)")
    for r in replay_files(paths, args.xt_grid, workers=args.workers):
        print(json.dumps(summary(r)), flush=True)


if __name__ == "__main__":
    main()
