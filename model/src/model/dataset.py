"""The goal model's dataset: features and labels for each team at each tick.

    uv run python -m model.dataset          # writes data/model/train.npz and test.npz

Each exported match is replayed through the engine offline (engine.backtest),
and at every tick from 15 minutes on, each team gets one row: its features as
the engine computes them live (engine.features), and whether it scored in the
next 5 and 10 minutes of play. Ticks are every 30 seconds, so a match gives
about 400 rows, and consecutive rows of a team overlap heavily: they are
grouped by match whenever the data is split.

Labels look at goals after the tick, [t + 30s, t + horizon] (MIN_LEAD_S: a
goal sooner than that is the attack already under way, not something to warn
of); features only at events released by then. The full-time labels (`ft`,
for the full-time model, docs/MODEL.md step 7) are what a prediction market's
"another goal" contract pays on: a goal after the tick and by the end of
regulation (90 minutes plus stoppage; extra time doesn't count), by the team
and by either team. A match ends when it ends: a
tick at 88' has 2 minutes left to score in, and is labelled as such, exactly
like the rules' evaluation (scripts/evaluate_alerts.py).
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
from engine.backtest import MIN_LEAD_S, Step, read_feed, replay
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
TICK_S = 30.0
"""A row every 30s of play. The live engine ticks more often (engine.ticks.TICK_S),
but rows 5s apart are near-copies of each other: more of them would make
training slower, not better. The features are the same at any tick."""
HORIZONS_MIN = (5, 10)
LAST_REGULATION_PERIOD = 2


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
    ft: np.ndarray = field(default_factory=lambda: np.zeros((0, 2), dtype=bool))
    """Whether, after the tick and by the end of regulation, the team scores
    (column 0) and anyone scores (column 1). False for rows in extra time,
    which `regulation` leaves out."""

    def __post_init__(self) -> None:
        if len(self.ft) != len(self.y):
            object.__setattr__(self, "ft", np.zeros((len(self.y), 2), dtype=bool))

    def __len__(self) -> int:
        return len(self.y)

    def label(self, horizon_min: int) -> np.ndarray:
        return self.y[:, HORIZONS_MIN.index(horizon_min)]

    def column(self, name: str) -> np.ndarray:
        return self.x[:, self.names.index(name)]

    @property
    def regulation(self) -> np.ndarray:
        """Rows in the 90 minutes plus stoppage time (not extra time)."""
        return np.asarray(self.column("extra_time") == 0)

    def subset(self, rows: np.ndarray) -> "Dataset":
        return Dataset(
            self.x[rows],
            self.y[rows],
            self.match_id[rows],
            self.team_id[rows],
            self.play_s[rows],
            self.names,
            self.meta,
            self.ft[rows],
        )

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
            ft=self.ft,
        )
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "Dataset":
        with np.load(path) as f:
            names = tuple(str(n) for n in f["names"])
            if names != FEATURE_NAMES or tuple(f["horizons"]) != HORIZONS_MIN or "ft" not in f:
                raise SystemExit(f"{path} is out of date with the engine's features; rebuild it")
            meta = json.loads(str(f["meta"])) if "meta" in f else {}
            return cls(
                f["x"], f["y"], f["match_id"], f["team_id"], f["play_s"], names, meta, f["ft"]
            )

    @classmethod
    def concat(cls, parts: Sequence["Dataset"]) -> "Dataset":
        return cls(
            np.concatenate([p.x for p in parts]),
            np.concatenate([p.y for p in parts]),
            np.concatenate([p.match_id for p in parts]),
            np.concatenate([p.team_id for p in parts]),
            np.concatenate([p.play_s for p in parts]),
            ft=np.concatenate([p.ft for p in parts]),
        )


def match_rows(path: Path, grid_path: Path = DEFAULT_GRID_PATH) -> Dataset:
    """Every row of one match's feed."""
    tracker = FeatureTracker()
    rows: list[tuple[float, int, list[float]]] = []
    regulation_end = 0.0

    def on_step(_: Pipeline, step: Step) -> None:
        nonlocal regulation_end
        if step.item.event.period <= LAST_REGULATION_PERIOD:
            regulation_end = max(regulation_end, step.item.play_s)
        if step.tick is None:
            return
        features = tracker.observe(step.tick)  # every tick, to keep the match totals
        if step.tick.play_s >= WARMUP_S:
            rows.extend((step.tick.play_s, team, f) for team, f in features.items())

    r = replay(
        read_feed(path), MetricsConfig(XTGrid.load(grid_path)), on_step=on_step, tick_s=TICK_S
    )
    play_s = np.array([t for t, _, _ in rows], dtype=np.float64)
    team_id = np.array([team for _, team, _ in rows], dtype=np.int64)
    goals = [(g.team_id, g.play_s) for g in r.goals]
    y = labels(play_s, team_id, goals)
    x = np.array([f for _, _, f in rows], dtype=np.float64).reshape(len(rows), len(FEATURE_NAMES))
    extra = x[:, FEATURE_NAMES.index("extra_time")] > 0
    ft = fulltime_labels(play_s, team_id, goals, regulation_end) & ~extra[:, None]
    match_id = np.full(len(rows), r.match_id, dtype=np.int64)
    return Dataset(x, y, match_id, team_id, play_s, ft=ft)


def labels(
    play_s: np.ndarray, team_id: np.ndarray, goals: Sequence[tuple[int, float]]
) -> np.ndarray:
    """For each row, whether its team scores in [play_s + MIN_LEAD_S,
    play_s + horizon] for each of HORIZONS_MIN. goals are (team it counts for,
    play_s)."""
    y = np.zeros((len(play_s), len(HORIZONS_MIN)), dtype=bool)
    for team, at in goals:
        for j, h in enumerate(HORIZONS_MIN):
            y[:, j] |= (team_id == team) & (play_s + MIN_LEAD_S <= at) & (at <= play_s + h * 60)
    return y


def fulltime_labels(
    play_s: np.ndarray, team_id: np.ndarray, goals: Sequence[tuple[int, float]], end_s: float
) -> np.ndarray:
    """For each row, whether its team (column 0) and anyone (column 1) scores in
    (play_s, end_s]: after the tick, by the end of regulation. Any goal after
    buying pays an "over" contract, so there's no MIN_LEAD_S here."""
    ft = np.zeros((len(play_s), 2), dtype=bool)
    for team, at in goals:
        later = (play_s < at) & (at <= end_s)
        ft[:, 0] |= later & (team_id == team)
        ft[:, 1] |= later
    return ft


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
    reg = d.regulation
    ft = (
        f"; by full time, the team scores again {d.ft[reg, 0].mean():.1%},"
        f" anyone {d.ft[reg, 1].mean():.1%}"
    )
    return f"{name}: {len(d):,} rows from {matches:,} matches; a team scores within {rates}{ft}"


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

    meta = {
        "xt_grid": args.xt_grid.name,
        "xt_grid_sha256": file_digest(args.xt_grid),
        "min_lead_s": str(MIN_LEAD_S),
    }
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
