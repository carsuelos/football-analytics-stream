"""Retune the rules (momentum, goal threat, control shift) on the training data.

    uv run python -m model.rules        # make rules: a few minutes the first time

The rules were set by hand in Phase 1, from the 2022 final. Here they are set
on the 2,552 training matches instead, and scored once on the World Cup:

1. Each match is replayed once through the engine, recording at every tick
   what the rules work from (RuleInputs): each team's pressure components over
   the last 5' and the 5' before, and since the last goal, with the xT added
   since then. Every rule can then be re-run for any settings in numpy, in
   seconds instead of a replay.
2. Pressure weights fitted (logistic regression, weights kept non-negative)
   so the pressure index ranks "this team scores in the next 10'" as well as
   it can, compared with the current ones. The rules are tuned on the current
   weights unless --fit-weights.
3. Goal threat is a logistic score of pressure and xT velocity. The mix of
   the two (which decides which alerts fire) is picked from a small grid,
   then a one-feature logistic regression on the mixed score sets the bias
   and scale, so the score is the chance of a goal in the next 10'.
4. Momentum and control shift: a small grid of their settings, each at the
   threshold giving --alerts-per-match alerts a match on the training set,
   keeping the settings with the best lift.
5. The engine itself re-runs the tuned rules on a sample of matches, to check
   the simulation raises exactly the same alerts.

Prints the engine's new defaults and writes data/model/rules.json.
"""

import argparse
import json
import math
import os
import random
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

import numpy as np
from engine.backtest import MIN_LEAD_S, Step, read_feed, replay
from engine.detectors import (
    ControlShift,
    ControlShiftConfig,
    DetectorConfig,
    Detectors,
    Ewma,
    GoalThreat,
    GoalThreatConfig,
    Momentum,
    MomentumConfig,
)
from engine.detectors.control_shift import back_to_back
from engine.detectors.goal_threat import since_last_goal
from engine.metrics import MetricsConfig, PressureComponents, PressureWeights, XTGrid, pressure
from engine.metrics.xt import DEFAULT_GRID_PATH, MIN_VELOCITY_MINUTES, xt_added
from engine.pipeline import Pipeline
from scipy.optimize import minimize
from sklearn.metrics import roc_auc_score

from model.dataset import OUT, TICK_S, WARMUP_S, file_digest, labels, quiet, test_paths, train_paths

COMPONENTS = tuple(f.name for f in fields(PressureComponents))
WINDOW_S = 300.0
"""Every rule looks at 5' windows."""
COOLDOWN_S = DetectorConfig().cooldown_s
ALERTS_PER_MATCH = 2.0
PARITY_MATCHES = 20
SEED = 2022
BOOTSTRAP = 1000
RULES = ("momentum_shift", "goal_threat", "control_shift")

MOMENTUM_GRID = [
    {"half_life_s": h, "std_floor": s}
    for h in (150.0, 300.0, 600.0, 1200.0)
    for s in (3.0, 6.0, 10.0, 15.0)
]
GOAL_THREAT_MIX = (0.0, 0.25, 0.5, 0.75, 1.0)
"""How much of goal threat's score comes from xT velocity rather than pressure."""
CONTROL_GRID = [
    {"smoothing": s, "previous_max": p} for s in (5.0, 10.0, 20.0) for p in (-0.2, 0.0, 0.2, 1.0)
]


@dataclass(frozen=True)
class RuleInputs:
    """What the rules see, for each team at each tick (in tick order within a match)."""

    match_id: np.ndarray
    team_id: np.ndarray
    play_s: np.ndarray
    own: np.ndarray
    """Pressure components over the last 5' (one column per COMPONENTS)."""
    opp: np.ndarray
    """The opponent's, over the same 5'."""
    own_prev: np.ndarray
    """Over the 5' before that; NaN until 10' of play."""
    opp_prev: np.ndarray
    own_since_goal: np.ndarray
    """Over the last 5', after any goal in it (goal threat's window)."""
    xt_since_goal: np.ndarray
    covered_since_goal: np.ndarray
    """Seconds of play that window covers."""
    y: np.ndarray
    """Whether the team scores within 5' and 10' (model.dataset.labels)."""
    goals: np.ndarray
    """(match_id, team_id, play_s) of each goal, for the team it counts for."""
    meta: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.play_s)

    @property
    def y5(self) -> np.ndarray:
        return self.y[:, 0]

    @property
    def y10(self) -> np.ndarray:
        return self.y[:, 1]

    def series(self) -> np.ndarray:
        """An id for each (match, team)."""
        pairs = np.stack([self.match_id, self.team_id], axis=1)
        return np.unique(pairs, axis=0, return_inverse=True)[1].ravel()

    def matches(self) -> int:
        return len(np.unique(self.match_id))

    def subset(self, match_ids: Sequence[int]) -> "RuleInputs":
        rows = np.isin(self.match_id, match_ids)
        goals = self.goals[np.isin(self.goals[:, 0], match_ids)]
        arrays = {
            f.name: getattr(self, f.name)[rows] for f in fields(self) if f.name not in _NOT_ROWS
        }
        return RuleInputs(**arrays, goals=goals, meta=self.meta)

    def save(self, path: Path, **meta: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        arrays = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "meta"}
        tmp = path.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, **arrays, components=np.array(COMPONENTS), meta=json.dumps(meta))
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "RuleInputs":
        with np.load(path) as f:
            if tuple(str(c) for c in f["components"]) != COMPONENTS:
                raise SystemExit(f"{path} is out of date with the engine; rebuild it (--rebuild)")
            arrays = {k: f[k] for k in f.files if k not in ("components", "meta")}
            return cls(**arrays, meta=json.loads(str(f["meta"])))

    @classmethod
    def concat(cls, parts: Sequence["RuleInputs"]) -> "RuleInputs":
        names = [f.name for f in fields(cls) if f.name != "meta"]
        arrays: dict[str, np.ndarray] = {
            n: np.concatenate([getattr(p, n) for p in parts]) for n in names
        }
        return cls(**arrays)  # type: ignore[arg-type]


_NOT_ROWS = ("goals", "meta")


def _components(c: PressureComponents) -> list[float]:
    return [float(getattr(c, n)) for n in COMPONENTS]


def match_inputs(path: Path, grid_path: Path = DEFAULT_GRID_PATH) -> RuleInputs:
    """Every tick of one match's feed, through the engine."""
    rows: list[tuple[float, int, list[float]]] = []
    nan = [math.nan] * len(COMPONENTS)

    def on_step(_: Pipeline, step: Step) -> None:
        tick = step.tick
        if tick is None:
            return
        ids = tick.team_ids
        last = pressure(tick.events(WINDOW_S), ids)
        halves = back_to_back(tick, WINDOW_S)
        before = pressure(halves[1], ids) if halves else None
        events, covered_s = since_last_goal(tick, WINDOW_S)
        since, xt = pressure(events, ids), xt_added(events, ids, tick.metrics.grid)
        for team, other in (ids, ids[::-1]):
            values = [
                *_components(last[team]),
                *_components(last[other]),
                *(_components(before[team]) if before else nan),
                *(_components(before[other]) if before else nan),
                *_components(since[team]),
                xt[team],
                covered_s,
            ]
            rows.append((tick.play_s, team, values))

    r = replay(
        read_feed(path), MetricsConfig(XTGrid.load(grid_path)), on_step=on_step, tick_s=TICK_S
    )
    k = len(COMPONENTS)
    v = np.array([values for _, _, values in rows], dtype=np.float64).reshape(len(rows), 5 * k + 2)
    play_s = np.array([t for t, _, _ in rows], dtype=np.float64)
    team_id = np.array([team for _, team, _ in rows], dtype=np.int64)
    goals = [(g.team_id, g.play_s) for g in r.goals]
    return RuleInputs(
        match_id=np.full(len(rows), r.match_id, dtype=np.int64),
        team_id=team_id,
        play_s=play_s,
        own=v[:, :k],
        opp=v[:, k : 2 * k],
        own_prev=v[:, 2 * k : 3 * k],
        opp_prev=v[:, 3 * k : 4 * k],
        own_since_goal=v[:, 4 * k : 5 * k],
        xt_since_goal=v[:, 5 * k],
        covered_since_goal=v[:, 5 * k + 1],
        y=labels(play_s, team_id, goals),
        goals=np.array([(r.match_id, t, s) for t, s in goals], dtype=np.float64).reshape(-1, 3),
    )


def build(paths: Sequence[Path], grid_path: Path, workers: int | None = None) -> RuleInputs:
    with ProcessPoolExecutor(workers or os.cpu_count(), initializer=quiet) as pool:
        parts = list(pool.map(match_inputs, paths, [grid_path] * len(paths), chunksize=4))
    return RuleInputs.concat(parts)


# The rules, re-run offline. Each gives a score per row, firing when it is at
# or above the threshold (NaN never fires), exactly as the detectors decide.


def weight_vector(w: PressureWeights) -> np.ndarray:
    return np.array([getattr(w, n) for n in COMPONENTS])


def momentum_scores(d: RuleInputs, c: MomentumConfig, w: PressureWeights) -> np.ndarray:
    """z of each team's pressure against its own EWMA baseline (Momentum)."""
    x = (d.own @ weight_vector(w)).tolist()
    play_s, series = d.play_s.tolist(), d.series().tolist()
    z = [math.nan] * len(x)
    baselines: dict[int, Ewma] = {}
    for i, key in enumerate(series):
        b = baselines.get(key)
        if b is None:
            b = baselines[key] = Ewma(c.half_life_s)
        if b.mean is not None and play_s[i] >= c.warmup_s:
            z[i] = (x[i] - b.mean) / max(b.std, c.std_floor)
        b.add(x[i], play_s[i])
    return np.array(z)


def goal_threat_inputs(d: RuleInputs, w: PressureWeights) -> tuple[np.ndarray, np.ndarray]:
    """Pressure index and xT velocity since the last goal (GoalThreat)."""
    velocity = d.xt_since_goal / np.maximum(d.covered_since_goal / 60, MIN_VELOCITY_MINUTES)
    return d.own_since_goal @ weight_vector(w), velocity


def goal_threat_scores(d: RuleInputs, c: GoalThreatConfig, w: PressureWeights) -> np.ndarray:
    press, velocity = goal_threat_inputs(d, w)
    logit = (
        c.bias + c.pressure_weight * press / c.pressure_scale + c.xt_weight * velocity / c.xt_scale
    )
    return 1 / (1 + np.exp(-logit))


def control_shift_scores(d: RuleInputs, c: ControlShiftConfig, w: PressureWeights) -> np.ndarray:
    """The pressure balance over the last 5', where it was at most
    previous_max the 5' before (ControlShift); NaN elsewhere."""
    v = weight_vector(w)

    def balance(own: np.ndarray, opp: np.ndarray) -> np.ndarray:
        a, b = own @ v, opp @ v
        result: np.ndarray = (a - b) / (a + b + c.smoothing)
        return result

    now, before = balance(d.own, d.opp), balance(d.own_prev, d.opp_prev)
    with np.errstate(invalid="ignore"):
        return np.where(before <= c.previous_max, now, np.nan)


def fire(d: RuleInputs, score: np.ndarray, threshold: float) -> np.ndarray:
    """Rows where an alert fires: score at or above threshold, at most once
    per team per COOLDOWN_S, like the detectors."""
    fired = np.zeros(len(d), dtype=bool)
    with np.errstate(invalid="ignore"):
        candidates = np.flatnonzero(score >= threshold)
    series, play_s = d.series()[candidates].tolist(), d.play_s[candidates].tolist()
    last: dict[int, float] = {}
    for i, key, t in zip(candidates.tolist(), series, play_s, strict=True):
        if key in last and t - last[key] < COOLDOWN_S:
            continue
        last[key] = t
        fired[i] = True
    return fired


def threshold_for(d: RuleInputs, score: np.ndarray, per_match: float) -> float:
    """The lowest threshold at which alerts fire at most per_match times a
    match (by bisection over the scores' range)."""
    finite = score[np.isfinite(score)]
    lo, hi = float(finite.min()), float(finite.max())
    matches = d.matches()
    for _ in range(40):
        mid = (lo + hi) / 2
        if fire(d, score, mid).sum() / matches > per_match:
            lo = mid
        else:
            hi = mid
    return hi


@dataclass(frozen=True)
class Score:
    """How the alerts fired at a threshold did."""

    threshold: float
    per_match: float
    alerts: int
    scores_5: float
    lift_5: float
    scores_10: float
    lift_10: float
    lift_10_ci: tuple[float, float]
    covered: float
    """Share of goals after 15' with an alert for the scorer from 10' to 30s before."""
    reactive: float
    """Share of alerts within 5' after the team scored."""


def score(d: RuleInputs, fired: np.ndarray, threshold: float) -> Score:
    after = d.play_s >= WARMUP_S
    base5, base10 = d.y5[after].mean(), d.y10[after].mean()
    n = int(fired.sum())
    ids, match_of = np.unique(d.match_id, return_inverse=True)

    def per_match(v: np.ndarray) -> np.ndarray:
        return np.bincount(match_of, weights=v.astype(np.float64), minlength=len(ids))

    hits, n_fired = per_match(fired & d.y10), per_match(fired)
    goals, rows = per_match(d.y10 & after), per_match(after)
    draws = np.random.default_rng(SEED).integers(0, len(ids), (BOOTSTRAP, len(ids)))
    with np.errstate(invalid="ignore", divide="ignore"):
        boot = (hits[draws].sum(1) / n_fired[draws].sum(1)) / (
            goals[draws].sum(1) / rows[draws].sum(1)
        )
    lo, hi = np.nanpercentile(boot, [2.5, 97.5]) if n else (math.nan, math.nan)
    rate5 = float(d.y5[fired].mean()) if n else math.nan
    rate10 = float(d.y10[fired].mean()) if n else math.nan
    return Score(
        threshold,
        n / len(ids),
        n,
        rate5,
        rate5 / base5,
        rate10,
        rate10 / base10,
        (float(lo), float(hi)),
        covered(d, fired),
        reactive(d, fired),
    )


def _alert_times(d: RuleInputs, fired: np.ndarray) -> dict[tuple[int, int], np.ndarray]:
    times: dict[tuple[int, int], list[float]] = {}
    for m, t, s in zip(d.match_id[fired], d.team_id[fired], d.play_s[fired], strict=True):
        times.setdefault((int(m), int(t)), []).append(float(s))
    return {k: np.array(v) for k, v in times.items()}


def covered(d: RuleInputs, fired: np.ndarray) -> float:
    times = _alert_times(d, fired)
    goals = [(int(m), int(t), s) for m, t, s in d.goals if s >= WARMUP_S]
    hit = 0
    for m, t, s in goals:
        a = times.get((m, t))
        hit += bool(a is not None and ((a >= s - 600) & (a <= s - MIN_LEAD_S)).any())
    return hit / len(goals) if goals else math.nan


def reactive(d: RuleInputs, fired: np.ndarray) -> float:
    by_team: dict[tuple[int, int], list[float]] = {}
    for m, t, s in d.goals:
        by_team.setdefault((int(m), int(t)), []).append(s)
    rows = np.flatnonzero(fired)
    if not len(rows):
        return math.nan
    n = 0
    for i in rows:
        goals = np.array(by_team.get((int(d.match_id[i]), int(d.team_id[i])), []))
        n += bool(((goals >= d.play_s[i] - 300) & (goals <= d.play_s[i])).any())
    return n / len(rows)


# Tuning.


def fit_pressure_weights(d: RuleInputs) -> PressureWeights:
    """Non-negative weights for which the index best predicts a goal in the
    next 10' (logistic regression on the components over the last 5'), scaled
    so the index averages what it did with the old weights."""
    rows = d.play_s >= WARMUP_S
    x, y = d.own[rows], d.y10[rows].astype(np.float64)
    sd = x.std(axis=0)
    xs = x / sd

    def loss(params: np.ndarray) -> tuple[float, np.ndarray]:
        z = params[0] + xs @ params[1:]
        p = 1 / (1 + np.exp(-z))
        ll = np.mean(np.logaddexp(0, z) - y * z)
        g = p - y
        return float(ll), np.concatenate([[g.mean()], xs.T @ g / len(y)])

    bounds = [(None, None)] + [(0.0, None)] * len(COMPONENTS)
    fit = minimize(loss, np.zeros(len(COMPONENTS) + 1), jac=True, bounds=bounds)
    raw = fit.x[1:] / sd
    raw *= (x @ weight_vector(PressureWeights())).mean() / (x @ raw).mean()
    return PressureWeights(**{n: _round(float(v)) for n, v in zip(COMPONENTS, raw, strict=True)})


def fit_goal_threat(
    d: RuleInputs, w: PressureWeights, per_match: float
) -> tuple[GoalThreatConfig, list[tuple[dict[str, float], Score]]]:
    """Goal threat's score is sigmoid(bias + a * pressure + b * xT velocity),
    each feature divided by its spread. Which alerts fire depends only on the
    mix of a and b, so the mix is picked like the other rules' settings: the
    best 10' lift at per_match alerts. Then bias and scale are fitted by
    logistic regression on the mixed score, so the score is the chance of a
    goal in the next 10'."""
    press, velocity = goal_threat_inputs(d, w)
    sp, sv = _round(float(press.std())), _round(float(velocity.std()))
    tried = []
    for mix in GOAL_THREAT_MIX:
        s = (1 - mix) * press / sp + mix * velocity / sv
        t = threshold_for(d, s, per_match)
        tried.append(({"xt_share": mix}, score(d, fire(d, s, t), t)))
    mix = max(tried, key=lambda st: st[1].lift_10)[0]["xt_share"]
    x = (1 - mix) * press / sp + mix * velocity / sv
    y = d.y10.astype(np.float64)

    def loss(params: np.ndarray) -> tuple[float, np.ndarray]:
        z = params[0] + params[1] * x
        g = 1 / (1 + np.exp(-z)) - y
        return float(np.mean(np.logaddexp(0, z) - y * z)), np.array([g.mean(), (g * x).mean()])

    bias, slope = minimize(loss, np.zeros(2), jac=True).x
    c = GoalThreatConfig(
        bias=_round(bias),
        pressure_weight=_round(slope * (1 - mix)),
        pressure_scale=sp,
        xt_weight=_round(slope * mix),
        xt_scale=sv,
    )
    t = threshold_for(d, goal_threat_scores(d, c, w), per_match)
    return replace(c, threshold=_round(t)), tried


def tune_grid[C: (MomentumConfig, ControlShiftConfig)](
    d: RuleInputs,
    w: PressureWeights,
    default: C,
    grid: list[dict[str, float]],
    scores: Callable[[RuleInputs, C, PressureWeights], np.ndarray],
    per_match: float,
) -> tuple[C, list[tuple[dict[str, float], Score]]]:
    """Each setting at the threshold for per_match alerts; the best by 10' lift."""
    tried = []
    for settings in grid:
        c = replace(default, **settings)
        s = scores(d, c, w)
        t = _round(threshold_for(d, s, per_match))
        tried.append((settings, score(d, fire(d, s, t), t)))
    best = max(tried, key=lambda st: st[1].lift_10)
    return replace(default, **best[0], threshold=best[1].threshold), tried


@dataclass(frozen=True)
class Rules:
    weights: PressureWeights
    momentum: MomentumConfig
    goal_threat: GoalThreatConfig
    control_shift: ControlShiftConfig

    def scores(self, d: RuleInputs) -> dict[str, tuple[np.ndarray, float]]:
        w = self.weights
        return {
            "momentum_shift": (momentum_scores(d, self.momentum, w), self.momentum.threshold),
            "goal_threat": (goal_threat_scores(d, self.goal_threat, w), self.goal_threat.threshold),
            "control_shift": (
                control_shift_scores(d, self.control_shift, w),
                self.control_shift.threshold,
            ),
        }

    def at_volume(self, d: RuleInputs, per_match: float) -> "Rules":
        """The same settings, with each threshold set for per_match alerts on d."""
        t = {
            name: _round(threshold_for(d, s, per_match)) for name, (s, _) in self.scores(d).items()
        }
        return replace(
            self,
            momentum=replace(self.momentum, threshold=t["momentum_shift"]),
            goal_threat=replace(self.goal_threat, threshold=t["goal_threat"]),
            control_shift=replace(self.control_shift, threshold=t["control_shift"]),
        )

    def evaluate(self, d: RuleInputs) -> dict[str, Score]:
        out, together = {}, np.zeros(len(d), dtype=bool)
        for name, (s, t) in self.scores(d).items():
            fired = fire(d, s, t)
            together |= fired
            out[name] = score(d, fired, t)
        out["rules"] = score(d, together, math.nan)
        return out

    def alerts(self, d: RuleInputs) -> set[tuple[str, int, int, float]]:
        """(type, match, team, play_s) of every alert, from the simulation."""
        found = set()
        for name, (s, t) in self.scores(d).items():
            fired = fire(d, s, t)
            for m, team, at in zip(
                d.match_id[fired], d.team_id[fired], d.play_s[fired], strict=True
            ):
                found.add((name, int(m), int(team), float(at)))
        return found

    def engine_alerts(self, path: Path, grid_path: Path) -> set[tuple[str, int, int, float]]:
        """The same, from the engine's own detectors replaying the feed."""
        detectors = Detectors(
            [
                Momentum(self.momentum),
                GoalThreat(self.goal_threat),
                ControlShift(self.control_shift),
            ]
        )
        r = replay(
            read_feed(path),
            MetricsConfig(XTGrid.load(grid_path), self.weights),
            detectors=detectors,
            tick_s=TICK_S,
        )
        return {(a.alert.type.value, r.match_id, a.alert.team_id, a.play_s) for a in r.alerts}


PHASE_2_RULES = Rules(
    PressureWeights(),
    MomentumConfig(half_life_s=600.0, std_floor=3.0, threshold=2.0),
    GoalThreatConfig(
        bias=-3.0,
        pressure_weight=1.5,
        pressure_scale=18.0,
        xt_weight=1.5,
        xt_scale=0.05,
        threshold=0.5,
    ),
    ControlShiftConfig(smoothing=5.0, threshold=0.5, previous_max=-0.2),
)
"""The hand-set rules before this tuning, to compare with."""


def _round(x: float, digits: int = 3) -> float:
    """To 3 significant digits, for readable defaults."""
    return float(f"{x:.{digits}g}")


def check_parity(
    rules: Rules, d: RuleInputs, paths: Sequence[Path], grid_path: Path, workers: int | None
) -> int:
    """Raise if the engine's detectors and the simulation disagree on any
    alert in these matches; return how many alerts they agreed on."""
    with ProcessPoolExecutor(workers or os.cpu_count(), initializer=quiet) as pool:
        found = list(pool.map(rules.engine_alerts, paths, [grid_path] * len(paths)))
    engine = set().union(*found)
    ids = sorted({m for _, m, _, _ in engine} | {int(p.stem) for p in paths})
    simulated = rules.alerts(d.subset(ids))
    if engine != simulated:
        diff = sorted(engine ^ simulated)[:10]
        raise SystemExit(f"the simulation and the engine disagree, e.g. {diff}")
    return len(engine)


def table(rows: list[tuple[str, Score]]) -> str:
    lines = [
        f"{'':30}{'thresh':>8}{'a match':>8}{'alerts':>7}{'in 5':>7}{'lift':>6}"
        f"{'in 10':>7}{'lift':>6}{'95%':>12}{'goals':>7}{'reactive':>9}"
    ]
    for name, s in rows:
        lines.append(
            f"{name:30}{s.threshold:8.3g}{s.per_match:8.1f}{s.alerts:7d}{s.scores_5:7.1%}"
            f"{s.lift_5:6.2f}{s.scores_10:7.1%}{s.lift_10:6.2f}"
            f"{s.lift_10_ci[0]:6.2f}-{s.lift_10_ci[1]:.2f}{s.covered:7.0%}{s.reactive:9.0%}"
        )
    return "\n".join(lines)


def index_auc(d: RuleInputs, w: PressureWeights) -> float:
    rows = d.play_s >= WARMUP_S
    return float(roc_auc_score(d.y10[rows], d.own[rows] @ weight_vector(w)))


def load_or_build(
    path: Path, paths: Callable[[], list[Path]], grid: Path, rebuild: bool, workers: int | None
) -> RuleInputs:
    if path.exists() and not rebuild:
        d = RuleInputs.load(path)
        # Rebuilt when the grid or the labels' lead time changes.
        if d.meta.get("xt_grid_sha256") == file_digest(grid) and d.meta.get("min_lead_s") == str(
            MIN_LEAD_S
        ):
            return d
    print(f"recording the rules' inputs into {path}…", flush=True)
    d = build(paths(), grid, workers)
    d.save(path, xt_grid=grid.name, xt_grid_sha256=file_digest(grid), min_lead_s=str(MIN_LEAD_S))
    return RuleInputs.load(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--data", type=Path, default=OUT, metavar="DIR")
    parser.add_argument("--xt-grid", type=Path, default=DEFAULT_GRID_PATH, metavar="FILE")
    parser.add_argument("--alerts-per-match", type=float, default=ALERTS_PER_MATCH)
    parser.add_argument("--rebuild", action="store_true", help="record the inputs again")
    parser.add_argument(
        "--fit-weights", action="store_true", help="tune the rules on fitted pressure weights"
    )
    parser.add_argument("--workers", type=int)
    args = parser.parse_args()
    per_match = args.alerts_per_match

    train = load_or_build(
        args.data / "rules_train.npz", train_paths, args.xt_grid, args.rebuild, args.workers
    )
    test = load_or_build(
        args.data / "rules_test.npz", test_paths, args.xt_grid, args.rebuild, args.workers
    )
    print(f"train: {len(train):,} rows from {train.matches():,} matches; test: {test.matches()}")

    fitted = fit_pressure_weights(train)
    print("\nfitted pressure weights:", asdict(fitted))
    print(
        "pressure index AUC for a goal in 10' (train, test):"
        f" current {index_auc(train, PressureWeights()):.3f},"
        f" {index_auc(test, PressureWeights()):.3f};"
        f" fitted {index_auc(train, fitted):.3f}, {index_auc(test, fitted):.3f}"
    )
    weights = fitted if args.fit_weights else PressureWeights()

    goal_threat, goal_threat_tried = fit_goal_threat(train, weights, per_match)
    momentum, momentum_tried = tune_grid(
        train, weights, PHASE_2_RULES.momentum, MOMENTUM_GRID, momentum_scores, per_match
    )
    control, control_tried = tune_grid(
        train, weights, PHASE_2_RULES.control_shift, CONTROL_GRID, control_shift_scores, per_match
    )
    tuned = Rules(weights, momentum, goal_threat, control)

    print(f"\nmomentum at {per_match:g} a match (train):")
    print(table([(json.dumps(s), sc) for s, sc in momentum_tried]))
    print(f"\ngoal threat at {per_match:g} a match (train):")
    print(table([(json.dumps(s), sc) for s, sc in goal_threat_tried]))
    print(f"\ncontrol shift at {per_match:g} a match (train):")
    print(table([(json.dumps(s), sc) for s, sc in control_tried]))

    old_at_volume = PHASE_2_RULES.at_volume(train, per_match)
    results: dict[str, dict[str, dict[str, object]]] = {}
    labelled = (("old", PHASE_2_RULES), (f"old at {per_match:g}", old_at_volume), ("new", tuned))
    for split, d in (("train", train), ("test", test)):
        rows = []
        for label, rules in labelled:
            for name, s in rules.evaluate(d).items():
                rows.append((f"{label} {name}", s))
                results.setdefault(split, {})[f"{label} {name}"] = asdict(s)
        print(f"\n{split}:")
        print(table(rows))

    sample = random.Random(SEED).sample(train_paths(), PARITY_MATCHES)
    agreed = check_parity(tuned, train, sample, args.xt_grid, args.workers)
    print(
        f"\nthe engine raises the same {agreed} alerts as the simulation on {len(sample)} matches"
    )

    print("\nthe engine's new defaults:")
    for c in (weights, momentum, goal_threat, control):
        print(f"  {c!r}")
    out = args.data / "rules.json"
    configs = {
        "weights": asdict(weights),
        "momentum": asdict(momentum),
        "goal_threat": asdict(goal_threat),
        "control_shift": asdict(control),
    }
    out.write_text(json.dumps({"configs": configs, "results": results}, indent=1) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
