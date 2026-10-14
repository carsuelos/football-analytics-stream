"""Expected threat (xT) computed from our own data: Karun Singh's Markov model.

    uv run python -m model.xt                      # train on data/training, test on the World Cup

The pitch is split into the engine's 12x8 grid. When a team has the ball in
zone z, its next action is either a shot, with probability s[z], or a move (a
pass or carry), with probability m[z] = 1 - s[z]. A shot scores with
probability g[z]. A move ends in zone z' with probability T[z, z'], counting
only moves that keep the ball: a failed pass loses it, and is worth nothing.
So the chance of scoring before losing the ball from z is

    xT[z] = s[z] * g[z] + m[z] * sum over z' of T[z, z'] * xT[z']

which is solved by iterating from xT = 0: after k iterations, xT[z] is the
chance of scoring within k actions. All the counts come from the canonical
events, so the grid is learnt from the same data, in the same coordinates, as
the engine sees. The counts are mirrored across the pitch's length before
solving (left and right are the same), which halves the noise in each zone.

The published grid (Karun Singh's, from Wyscout data) is the comparison. Both
are scored on the test matches by how well they predict whether a possession
ends in a goal from each action's zone (see score_grid).
"""

import argparse
import json
import math
import os
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from engine.metrics.pitch import GRID_COLS, GRID_ROWS, grid_cell
from engine.metrics.xt import DEFAULT_GRID_PATH, XTGrid

ROOT = Path(__file__).resolve().parents[3]
TRAIN_FEEDS = ROOT / "data" / "training" / "feeds"
TEST_FEEDS = ROOT / "data" / "feeds"
DEFAULT_OUT = ROOT / "model" / "artifacts" / "xt_statsbomb_12x8.json"
ZONES = GRID_COLS * GRID_ROWS
PENALTY_SPOT = (108.0, 40.0)
SHOOTOUT_PERIOD = 5
MOVE_TYPES = ("pass", "carry")

Event = dict[str, Any]


def zone(location: Sequence[float]) -> int:
    """The index of a location's grid cell: row * GRID_COLS + col."""
    col, row = grid_cell((location[0], location[1]))
    return row * GRID_COLS + col


def is_penalty(ev: Event) -> bool:
    """A shot from the penalty spot. The canonical schema has no shot type, but
    open-play shots from exactly the spot are vanishingly rare."""
    loc = ev.get("location")
    return ev["type"] == "shot" and loc is not None and tuple(loc[:2]) == PENALTY_SPOT


def read_events(path: Path) -> Iterator[Event]:
    """The events in a feed file, as plain dicts (much faster than the models)."""
    with path.open() as f:
        for line in f:
            msg = json.loads(line)
            ev = msg.get("event")
            if ev is not None and ev["period"] != SHOOTOUT_PERIOD:
                yield ev


@dataclass
class Counts:
    """What the Markov model needs, per zone."""

    shots: np.ndarray  # (ZONES,)
    goals: np.ndarray  # (ZONES,)
    moves: np.ndarray  # (ZONES,) every pass or carry, kept or lost
    transitions: np.ndarray  # (ZONES, ZONES) moves that kept the ball, by start and end

    @classmethod
    def zero(cls) -> "Counts":
        return cls(np.zeros(ZONES), np.zeros(ZONES), np.zeros(ZONES), np.zeros((ZONES, ZONES)))

    def __iadd__(self, other: "Counts") -> "Counts":
        self.shots += other.shots
        self.goals += other.goals
        self.moves += other.moves
        self.transitions += other.transitions
        return self

    def mirrored(self) -> "Counts":
        """These counts plus their mirror image across the pitch: left and
        right are the same to the model, so this halves the noise."""
        flip = np.arange(ZONES).reshape(GRID_ROWS, GRID_COLS)[::-1].reshape(-1)
        return Counts(
            self.shots + self.shots[flip],
            self.goals + self.goals[flip],
            self.moves + self.moves[flip],
            self.transitions + self.transitions[np.ix_(flip, flip)],
        )

    def add(self, ev: Event) -> None:
        loc = ev.get("location")
        if loc is None:
            return
        z = zone(loc)
        if ev["type"] == "shot" and not is_penalty(ev):
            self.shots[z] += 1
            self.goals[z] += ev["shot"]["outcome"] == "goal"
        elif ev["type"] in MOVE_TYPES:
            self.moves[z] += 1
            end = ev.get("end_location")
            if end is not None and ev.get("outcome") != "failure":
                self.transitions[z, zone(end)] += 1


def count_file(path: Path) -> Counts:
    c = Counts.zero()
    for ev in read_events(path):
        c.add(ev)
    return c


def count(paths: Sequence[Path], workers: int | None = None) -> Counts:
    total = Counts.zero()
    with ProcessPoolExecutor(max_workers=workers or os.cpu_count()) as pool:
        for c in pool.map(count_file, paths, chunksize=16):
            total += c
    return total


@dataclass(frozen=True)
class Solution:
    xt: np.ndarray  # (GRID_ROWS, GRID_COLS)
    iterations: int
    shoot: np.ndarray  # s[z]
    score: np.ndarray  # g[z]
    move: np.ndarray  # m[z]


def solve(c: Counts, tol: float = 1e-10, max_iterations: int = 10_000) -> Solution:
    """Iterate xT = s * g + m * T @ xT from zero until it stops changing."""
    actions = c.shots + c.moves
    with np.errstate(divide="ignore", invalid="ignore"):
        shoot = np.where(actions > 0, c.shots / actions, 0.0)
        move = np.where(actions > 0, c.moves / actions, 0.0)
        score = np.where(c.shots > 0, c.goals / c.shots, 0.0)
        transition = np.where(c.moves[:, None] > 0, c.transitions / c.moves[:, None], 0.0)
    payoff = shoot * score
    xt = np.zeros(ZONES)
    iterations = 0
    while iterations < max_iterations:
        iterations += 1
        nxt = payoff + move * (transition @ xt)
        done = np.max(np.abs(nxt - xt)) < tol
        xt = nxt
        if done:
            break
    shape = (GRID_ROWS, GRID_COLS)
    return Solution(
        xt.reshape(shape),
        iterations,
        shoot.reshape(shape),
        score.reshape(shape),
        move.reshape(shape),
    )


def possession_outcomes(paths: Iterable[Path]) -> Iterator[tuple[int, bool]]:
    """(zone, whether the possession ended in a goal for the team in it) for
    every pass, carry and non-penalty shot by the team in possession."""
    for path in paths:
        events = list(read_events(path))
        scored: set[int] = set()
        for ev in events:
            if ev["type"] == "shot" and ev["shot"]["outcome"] == "goal" and not is_penalty(ev):
                scored.add(ev["possession_id"])
        for ev in events:
            loc = ev.get("location")
            if (
                loc is not None
                and ev["team"]["id"] == ev["possession_team_id"]
                and (ev["type"] in MOVE_TYPES or (ev["type"] == "shot" and not is_penalty(ev)))
            ):
                yield zone(loc), ev["possession_id"] in scored


@dataclass(frozen=True)
class Score:
    """How well a grid predicts possession outcomes, as a probability per zone."""

    actions: int
    goal_rate: float
    brier: float
    brier_skill: float
    """1 - brier / the brier of predicting goal_rate everywhere: 0 is no better
    than knowing nothing about where the ball is, 1 is perfect."""
    log_loss: float
    calibration: float
    """Sum of predictions over sum of outcomes: 1.0 is calibrated on average."""


def score_grid(xt: np.ndarray, outcomes: Sequence[tuple[int, bool]], min_col: int = 0) -> Score:
    """Score xt on the outcomes of actions in columns min_col and up."""
    chosen = [(z, g) for z, g in outcomes if z % GRID_COLS >= min_col]
    zones = np.array([z for z, _ in chosen])
    y = np.array([g for _, g in chosen], dtype=float)
    p = np.clip(xt.reshape(-1)[zones], 1e-6, 1 - 1e-6)
    rate = float(y.mean())
    brier = float(np.mean((p - y) ** 2))
    base = float(np.mean((rate - y) ** 2))
    log_loss = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    return Score(len(y), rate, brier, 1 - brier / base, log_loss, float(p.sum() / y.sum()))


def feed_files(directory: Path) -> list[Path]:
    paths = sorted(directory.glob("*.jsonl"))
    if not paths:
        raise SystemExit(f"no feeds in {directory}; run: make fetch-training export")
    return paths


def format_grid(xt: np.ndarray) -> str:
    """Rows across the pitch, columns along it, attacking left to right; in %."""
    return "\n".join(" ".join(f"{100 * v:5.1f}" for v in row) for row in xt)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m model.xt", description=__doc__.split("\n")[0])
    parser.add_argument("--train", type=Path, default=TRAIN_FEEDS, metavar="DIR")
    parser.add_argument("--test", type=Path, default=TEST_FEEDS, metavar="DIR")
    parser.add_argument("--published", type=Path, default=DEFAULT_GRID_PATH, metavar="PATH")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, metavar="PATH")
    args = parser.parse_args(argv)

    train = feed_files(args.train)
    counts = count(train)
    solution = solve(counts.mirrored())
    print(
        f"Trained on {len(train)} matches: {int(counts.moves.sum())} passes and carries, "
        f"{int(counts.shots.sum())} shots, {int(counts.goals.sum())} goals; "
        f"converged in {solution.iterations} iterations.\n"
    )
    print("Our xT (% chance of scoring before losing the ball; attacking left to right):")
    print(format_grid(solution.xt))

    published = np.array(XTGrid.load(args.published).rows)
    print("\nPublished xT (Karun Singh):")
    print(format_grid(published))
    diff = solution.xt - published
    corr = float(np.corrcoef(solution.xt.reshape(-1), published.reshape(-1))[0, 1])
    print(
        f"\nCorrelation {corr:.3f}; ours minus published: mean {100 * diff.mean():+.2f} "
        f"points, largest {100 * diff.max():+.1f} / {100 * diff.min():+.1f}"
    )

    outcomes = list(possession_outcomes(feed_files(args.test)))
    print(
        f"\nTest: does the possession end in a goal? {len(outcomes)} actions in "
        f"{len(feed_files(args.test))} matches."
    )
    print(
        f"{'actions':16}{'grid':11}{'goal rate':>10}{'brier':>10}{'skill':>8}"
        f"{'log loss':>10}{'calibration':>13}"
    )
    for label, min_col in (("all", 0), ("final third", 8)):
        for name, grid in (("ours", solution.xt), ("published", published)):
            s = score_grid(grid, outcomes, min_col)
            print(
                f"{label:16}{name:11}{s.goal_rate:10.2%}{s.brier:10.5f}{s.brier_skill:8.3f}"
                f"{s.log_loss:10.4f}{s.calibration:13.2f}"
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows = [[round(float(v), 6) for v in row] for row in solution.xt]
    assert all(math.isfinite(v) for row in rows for v in row)
    args.out.write_text(json.dumps(rows) + "\n")
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
