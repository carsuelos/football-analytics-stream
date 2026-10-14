"""The goal model's dataset: features and labels for each team at each tick.

    uv run python -m model.dataset          # writes data/model/train.npz and test.npz

Each exported match is replayed through the engine offline (engine.backtest),
and at every tick from 15 minutes on, each team gets one row: its features as
the engine computes them live (engine.features), and whether it scored in the
next 5 and 10 minutes of play. Ticks are every 30 seconds, so a match gives
about 400 rows, and consecutive rows of a team overlap heavily: they are
grouped by match whenever the data is split.

Labels look at goals after the tick, (t, t + horizon]; features only at events
released by then. A match ends when it ends: a tick at 88' has 2 minutes left
to score in, and is labelled as such, exactly like the rules' evaluation
(scripts/evaluate_alerts.py).
"""

import argparse
import hashlib
import json
import logging
import os
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from engine.backtest import Step, read_feed, replay
from engine.features import FEATURE_NAMES, FeatureTracker
from engine.metrics import MetricsConfig, XTGrid
from engine.metrics.xt import DEFAULT_GRID_PATH
from engine.pipeline import Pipeline
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[3]
TRAIN_FEEDS = ROOT / "data" / "training" / "feeds"
TEST_FEEDS = ROOT / "data" / "feeds"
TEST_COMPETITION = ("FIFA World Cup", "2022")
OUT = ROOT / "data" / "model"
WARMUP_S = 15 * 60.0
HORIZONS_MIN = (5, 10)


@dataclass(frozen=True)
class Dataset:
    """One row per team per tick."""

    x: np.ndarray
    """Features, in `names` order."""
    y: np.ndarray
    """Whether the team scored within each of HORIZONS_MIN (bool, one column each)."""
    match_id: np.ndarray
    team_id: np.ndarray
    play_s: np.ndarray
    names: tuple[str, ...] = FEATURE_NAMES
    meta: dict[str, str] = field(default_factory=dict)
    """How it was built, e.g. the xT grid's digest (see main)."""

    def __len__(self) -> int:
        return len(self.y)

    def label(self, horizon_min: int) -> np.ndarray:
        return self.y[:, HORIZONS_MIN.index(horizon_min)]

    def column(self, name: str) -> np.ndarray:
        return self.x[:, self.names.index(name)]

    def save(self, path: Path, **meta: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp.npz")
        np.savez_compressed(
            tmp,
            x=self.x,
            y=self.y,
            match_id=self.match_id,
            team_id=self.team_id,
            play_s=self.play_s,
            names=np.array(self.names),
            horizons=np.array(HORIZONS_MIN),
            meta=np.array(json.dumps(meta)),
        )
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "Dataset":
        with np.load(path) as f:
            names = tuple(str(n) for n in f["names"])
            if names != FEATURE_NAMES or tuple(f["horizons"]) != HORIZONS_MIN:
                raise SystemExit(f"{path} is out of date with the engine's features; rebuild it")
            meta = json.loads(str(f["meta"])) if "meta" in f else {}
            return cls(f["x"], f["y"], f["match_id"], f["team_id"], f["play_s"], names, meta)

    @classmethod
    def concat(cls, parts: Sequence["Dataset"]) -> "Dataset":
        return cls(
            np.concatenate([p.x for p in parts]),
            np.concatenate([p.y for p in parts]),
            np.concatenate([p.match_id for p in parts]),
            np.concatenate([p.team_id for p in parts]),
            np.concatenate([p.play_s for p in parts]),
        )


def match_rows(path: Path, grid_path: Path = DEFAULT_GRID_PATH) -> Dataset:
    """Every row of one match's feed."""
    tracker = FeatureTracker()
    rows: list[tuple[float, int, list[float]]] = []

    def on_step(_: Pipeline, step: Step) -> None:
        if step.tick is None:
            return
        features = tracker.observe(step.tick)  # every tick, to keep the match totals
        if step.tick.play_s >= WARMUP_S:
            rows.extend((step.tick.play_s, team, f) for team, f in features.items())

    r = replay(read_feed(path), MetricsConfig(XTGrid.load(grid_path)), on_step=on_step)
    play_s = np.array([t for t, _, _ in rows], dtype=np.float64)
    team_id = np.array([team for _, team, _ in rows], dtype=np.int64)
    y = labels(play_s, team_id, [(g.team_id, g.play_s) for g in r.goals])
    x = np.array([f for _, _, f in rows], dtype=np.float64).reshape(len(rows), len(FEATURE_NAMES))
    return Dataset(x, y, np.full(len(rows), r.match_id, dtype=np.int64), team_id, play_s)


def labels(
    play_s: np.ndarray, team_id: np.ndarray, goals: Sequence[tuple[int, float]]
) -> np.ndarray:
    """For each row, whether its team scores in (play_s, play_s + horizon] for
    each of HORIZONS_MIN. goals are (team it counts for, play_s)."""
    y = np.zeros((len(play_s), len(HORIZONS_MIN)), dtype=bool)
    for team, at in goals:
        for j, h in enumerate(HORIZONS_MIN):
            y[:, j] |= (team_id == team) & (play_s < at) & (at <= play_s + h * 60)
    return y


def quiet() -> None:
    """Silence the engine's warnings about late events, a few hundred over the training set."""
    logging.getLogger("engine").setLevel(logging.ERROR)


def build(paths: Sequence[Path], grid_path: Path, workers: int | None = None) -> Dataset:
    with ProcessPoolExecutor(workers or os.cpu_count(), initializer=quiet) as pool:
        parts = list(pool.map(match_rows, paths, [grid_path] * len(paths), chunksize=4))
    return Dataset.concat(parts)


def test_paths(feeds: Path = TEST_FEEDS) -> list[Path]:
    """The test matches: the 2022 World Cup's exported feeds."""
    listing = feeds / "matches.json"
    if not listing.exists():
        raise SystemExit(f"no {listing}; run: make fetch-data export")
    competition, season = TEST_COMPETITION
    infos = json.loads(listing.read_text())["matches"]
    return sorted(
        feeds / f"{m['match_id']}.jsonl"
        for m in infos
        if m["competition"] == competition and m["season"] == season
    )


def train_paths(feeds: Path = TRAIN_FEEDS) -> list[Path]:
    paths = sorted(feeds.glob("*.jsonl"))
    if not paths:
        raise SystemExit(f"no feeds in {feeds}; run: make fetch-training")
    return paths


def describe(name: str, d: Dataset) -> str:
    matches = len(np.unique(d.match_id))
    rates = ", ".join(f"{h}' {d.label(h).mean():.1%}" for h in HORIZONS_MIN)
    return f"{name}: {len(d):,} rows from {matches:,} matches; a team scores within {rates}"


def univariate(train: Dataset, test: Dataset, horizon_min: int = 10) -> str:
    """How well each feature alone ranks the rows (AUC; 0.5 is chance, below
    0.5 means higher values go with fewer goals)."""
    lines = [f"{'feature':20}{'train AUC':>10}{'test AUC':>10}{'train mean':>12}"]
    y_train, y_test = train.label(horizon_min), test.label(horizon_min)
    scored = []
    for name in FEATURE_NAMES:
        a = float(roc_auc_score(y_train, train.column(name)))
        b = float(roc_auc_score(y_test, test.column(name)))
        scored.append((abs(a - 0.5), name, a, b, float(train.column(name).mean())))
    for _, name, a, b, mean in sorted(scored, reverse=True):
        lines.append(f"{name:20}{a:10.3f}{b:10.3f}{mean:12.3f}")
    return "\n".join(lines)


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--train", type=Path, default=TRAIN_FEEDS, metavar="DIR")
    parser.add_argument("--test", type=Path, default=TEST_FEEDS, metavar="DIR")
    parser.add_argument("--xt-grid", type=Path, default=DEFAULT_GRID_PATH, metavar="FILE")
    parser.add_argument("--out", type=Path, default=OUT, metavar="DIR")
    parser.add_argument("--workers", type=int)
    args = parser.parse_args()

    meta = {"xt_grid": args.xt_grid.name, "xt_grid_sha256": file_digest(args.xt_grid)}
    test = build(test_paths(args.test), args.xt_grid, args.workers)
    test.save(args.out / "test.npz", **meta)
    print(describe("test", test), flush=True)
    train = build(train_paths(args.train), args.xt_grid, args.workers)
    train.save(args.out / "train.npz", **meta)
    print(describe("train", train))
    print(f"\nEach feature alone, scoring within {max(HORIZONS_MIN)}':")
    print(univariate(train, test))


if __name__ == "__main__":
    main()
