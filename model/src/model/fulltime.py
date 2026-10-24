"""The full-time model: will there be another goal before full time?

    uv run python -m model.fulltime        # after make dataset; about 5 minutes

The goal model (model.train) says when a team is likely to score soon: it fires
the alerts. A prediction market's "over" contract pays on something else: one
more goal, by the team ("Argentina over 2.5" at 2-2) or by anyone ("over 4.5"),
any time before the end of regulation (90 minutes plus stoppage). This model
prices those contracts: for a team at a tick, the probability that it scores
again before full time (`team`), and that anyone does (`game`).

How much time is left is most of the answer, and it isn't the minute: matches
used to end at about 95 minutes of play and since 2022 run to about 100 (the
World Cup's longer stoppage time). So the models get the **expected minutes
left** (engine.detectors.fulltime.minutes_left): from how long the matches of
that competition and season last on average (leaving the match itself out),
and how much a match varies around that. Live, the average is the recent
matches' (2023 on).

Models, compared as in model.train (cross-validation by match on the training
set, then the 2022 World Cup once), on regulation ticks only:

- clock (minute): the minute alone, with hinges (a broken line);
- clock (left): the expected minutes left alone, with hinges;
- game state: the minutes left and the score;
- curved (minute): every feature, with hinges on the minute (the goal model's shape);
- curved: every feature, with hinges on the minutes left;
- boosted: gradient-boosted trees on every feature and the minutes left, as a
  check for curves or a leak.

For the game, each model sees one team's row; a tick's probability is the mean
over its two rows, so it doesn't depend on which team is looking. It's also
compared with combining the team model's two probabilities as if the teams
scored independently: 1 - (1 - p_home)(1 - p_away).

Then: how calibrated each is at the moments the goal model alerts, which is
when a strategy would buy. The curved model is shipped to the engine
(engine/src/engine/detectors/fulltime_model.json), checked against scikit-learn.
"""

import argparse
import itertools
import json
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from engine.detectors.fulltime import DEFAULT_FULLTIME_PATH, MIN_LEFT, FullTimeModel
from engine.detectors.goal_chance import DEFAULT_MODEL_PATH, GoalModel
from engine.features import FEATURE_NAMES
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from model.dataset import OUT, TICK_S, TRAIN_FEEDS, WARMUP_S, Dataset
from model.train import (
    GAME_STATE,
    MINUTE_KNOTS,
    Fold,
    Hinges,
    Scores,
    Spec,
    boosted,
    columns,
    cross_validate,
    scores,
)

TARGETS = ("team", "game")
LEFT = "left"
LEFT_KNOTS = (3.0, 6.0, 10.0, 15.0, 25.0, 40.0, 60.0)
"""Hinges on the minutes left: closer together near the end, where each minute matters most."""
SHIPPED = "curved"
SHIPPED_C = 0.01
BINS = tuple(i / 10 for i in range(11))
MIN_GROUP = 10
"""A competition-season with fewer matches than this uses its year's average length instead."""
MODERN_FROM = 2023
"""Seasons from this year on have the longer stoppage time: their average
length is the one expected live."""
RESIDUAL_QUANTILES = tuple(np.arange(2.5, 100, 2.5))


@dataclass(frozen=True)
class Lengths:
    """How long matches last (minutes of play, stoppage time included)."""

    expected: dict[int, float]
    """Each training match's expected length: its competition-season's average without it."""
    residuals: tuple[float, ...]
    """Quantiles of (actual - expected) over the training matches."""
    modern: float
    """The average length of the matches from MODERN_FROM on: what's expected live."""
    actual: dict[int, float]


def match_lengths(d: Dataset) -> dict[int, float]:
    """Each match's length: its last regulation tick, plus half a tick (the end
    is somewhere in the next one)."""
    out: dict[int, float] = {}
    for m, t in zip(d.match_id, d.play_s, strict=True):
        out[int(m)] = max(out.get(int(m), 0.0), t / 60)
    return {m: v + TICK_S / 120 for m, v in out.items()}


def season_year(season: str) -> int:
    return int(season[:4])


def lengths(train: Dataset, feeds: Path = TRAIN_FEEDS) -> Lengths:
    info = {m["match_id"]: m for m in json.loads((feeds / "matches.json").read_text())["matches"]}
    actual = match_lengths(train)
    groups: dict[Any, list[int]] = {}
    years: dict[int, list[int]] = {}
    for m in actual:
        i = info[m]
        groups.setdefault((i["competition"], i["season"]), []).append(m)
        years.setdefault(season_year(i["season"]), []).append(m)

    def loo(ids: list[int], m: int) -> float:
        return (sum(actual[i] for i in ids) - actual[m]) / (len(ids) - 1)

    overall = list(actual)
    expected = {}
    for m in actual:
        i = info[m]
        group = groups[(i["competition"], i["season"])]
        year = years[season_year(i["season"])]
        ids = group if len(group) >= MIN_GROUP else year if len(year) >= MIN_GROUP else overall
        expected[m] = loo(ids, m)
    residuals = np.array([actual[m] - expected[m] for m in actual])
    modern = [actual[m] for m in actual if season_year(info[m]["season"]) >= MODERN_FROM]
    return Lengths(
        expected,
        tuple(float(q) for q in np.percentile(residuals, RESIDUAL_QUANTILES)),
        float(np.mean(modern)),
        actual,
    )


def left(minute: np.ndarray, end: np.ndarray, residuals: Sequence[float]) -> np.ndarray:
    """engine.detectors.fulltime.minutes_left for many rows at once."""
    out = np.empty(len(minute))
    r = np.asarray(residuals)
    for lo in range(0, len(minute), 100_000):
        m, e = minute[lo : lo + 100_000, None], end[lo : lo + 100_000, None]
        ahead = e + r[None, :] - m
        on = ahead > 0
        n = on.sum(axis=1)
        mean = np.where(on, ahead, 0).sum(axis=1) / np.maximum(n, 1)
        out[lo : lo + 100_000] = np.where(n > 0, mean, MIN_LEFT)
    return out


def with_left(d: Dataset, end: np.ndarray, residuals: Sequence[float]) -> Dataset:
    """d with the expected minutes left as an extra column."""
    x = np.column_stack([d.x, left(d.column("minute"), end, residuals)])
    return Dataset(x, d.y, d.match_id, d.team_id, d.play_s, (*d.names, LEFT), d.meta, d.ft)


def opponents(d: Dataset) -> np.ndarray:
    """For each row, the row of the other team at the same tick."""
    order = np.lexsort((d.team_id, d.play_s, d.match_id))
    a, b = order[0::2], order[1::2]
    if not (
        np.array_equal(d.match_id[a], d.match_id[b])
        and np.array_equal(d.play_s[a], d.play_s[b])
        and not np.any(d.team_id[a] == d.team_id[b])
    ):
        raise SystemExit("every tick should have a row for each team")
    opp = np.empty(len(d), dtype=np.int64)
    opp[a], opp[b] = b, a
    return opp


def curved(names: Sequence[str], hinge_on: str, knots: Sequence[float]) -> Any:
    """Standardized, L2-penalized logistic regression with hinges on one column."""

    def make(params: dict[str, Any]) -> Pipeline:
        return make_pipeline(
            Hinges(list(names).index(hinge_on), knots),
            StandardScaler(),
            LogisticRegression(C=params["C"], max_iter=3000),
        )

    return make


def specs() -> list[Spec]:
    every = (*FEATURE_NAMES, LEFT)
    state = (*GAME_STATE, LEFT)
    return [
        Spec(
            "clock (minute)", ("minute",), curved(("minute",), "minute", MINUTE_KNOTS), [{"C": 1.0}]
        ),
        Spec("clock (left)", (LEFT,), curved((LEFT,), LEFT, LEFT_KNOTS), [{"C": 1.0}]),
        Spec("game state", state, curved(state, LEFT, LEFT_KNOTS), [{"C": 1.0}]),
        Spec(
            "curved (minute)",
            FEATURE_NAMES,
            curved(FEATURE_NAMES, "minute", MINUTE_KNOTS),
            [{"C": SHIPPED_C}],
        ),
        Spec(
            SHIPPED, every, curved(every, LEFT, LEFT_KNOTS), [{"C": c} for c in (0.001, SHIPPED_C)]
        ),
        Spec(
            "boosted",
            every,
            boosted,
            [
                {
                    "learning_rate": 0.05,
                    "max_iter": 150,
                    "max_leaf_nodes": 8,
                    "min_samples_leaf": 500,
                }
            ],
        ),
    ]


def symmetric(p: np.ndarray, opp: np.ndarray) -> np.ndarray:
    """A game probability that doesn't depend on which team's row it came from."""
    return np.asarray((p + p[opp]) / 2)


def independent(p_team: np.ndarray, opp: np.ndarray) -> np.ndarray:
    """Anyone scores, if the two teams scored independently."""
    return np.asarray(1 - (1 - p_team) * (1 - p_team[opp]))


def reliability(y: np.ndarray, p: np.ndarray) -> list[tuple[str, int, float, float]]:
    out = []
    for lo, hi in itertools.pairwise(BINS):
        m = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        if m.any():
            out.append((f"{lo:.0%}-{hi:.0%}", int(m.sum()), float(p[m].mean()), float(y[m].mean())))
    return out


@dataclass(frozen=True)
class AtAlerts:
    rows: int
    actual: float
    predicted: dict[str, float]


def at_alerts(y: np.ndarray, preds: dict[str, np.ndarray], alerting: np.ndarray) -> AtAlerts:
    """Mean predictions and the actual rate over the rows where the goal model alerts."""
    return AtAlerts(
        int(alerting.sum()),
        float(y[alerting].mean()),
        {name: float(p[alerting].mean()) for name, p in preds.items()},
    )


def line(name: str, s: Scores) -> str:
    return f"{name:18}{s.skill:8.4f}{s.log_loss:10.4f}{s.auc:7.3f}{s.calibration:7.3f}"


def to_json(models: dict[str, Pipeline], train: Dataset, ls: Lengths) -> dict[str, Any]:
    parts = {}
    for target, model in models.items():
        _, scaler, regression = model.named_steps.values()
        parts[target] = {
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
            "coef": regression.coef_[0].tolist(),
            "intercept": float(regression.intercept_[0]),
            "base_rate": float(train.ft[:, TARGETS.index(target)].mean()),
        }
    return {
        "model": "logistic regressions with hinges on the expected minutes left"
        " (docs/MODEL.md, step 7)",
        "features": list(FEATURE_NAMES),
        "left_knots": list(LEFT_KNOTS),
        "end_min": round(ls.modern, 2),
        "end_residuals": [round(r, 3) for r in ls.residuals],
        **parts,
        "warmup_s": WARMUP_S,
        "xt_grid": train.meta.get("xt_grid", ""),
        "xt_grid_sha256": train.meta.get("xt_grid_sha256", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--data", type=Path, default=OUT, metavar="DIR")
    parser.add_argument("--out", type=Path, default=DEFAULT_FULLTIME_PATH, metavar="FILE")
    parser.add_argument("--results", type=Path, default=OUT / "fulltime.json", metavar="FILE")
    args = parser.parse_args()

    goal = GoalModel.load(DEFAULT_MODEL_PATH)
    raw = {}
    for name in ("train", "test"):
        d = Dataset.load(args.data / f"{name}.npz")
        raw[name] = d.subset(d.regulation)
    ls = lengths(raw["train"])
    test_actual = match_lengths(raw["test"])
    print(
        f"Match length (minutes of play): training {np.mean(list(ls.actual.values())):.1f}"
        f" on average, from {MODERN_FROM} {ls.modern:.1f};"
        f" the World Cup {np.mean(list(test_actual.values())):.1f}."
        f" A match varies around its competition's average by {ls.residuals[1]:+.1f}"
        f" to {ls.residuals[-2]:+.1f} (5th to 95th percentile)",
        flush=True,
    )
    end_train = np.array([ls.expected[int(m)] for m in raw["train"].match_id])
    train = with_left(raw["train"], end_train, ls.residuals)
    test = with_left(raw["test"], np.full(len(raw["test"]), ls.modern), ls.residuals)
    opp_train, opp_test = opponents(train), opponents(test)
    alerting = np.array([goal.probability(r.tolist()) >= goal.threshold for r in raw["test"].x])
    results: dict[str, Any] = {
        "lengths": {
            "modern": ls.modern,
            "residuals": ls.residuals,
            "test": float(np.mean(list(test_actual.values()))),
        },
        "cv": {},
        "test": {},
        "reliability": {},
        "at_alerts": {},
    }
    shipped: dict[str, Pipeline] = {}
    test_team: dict[str, np.ndarray] = {}

    for target in TARGETS:
        col = TARGETS.index(target)
        y, y_test = train.ft[:, col], test.ft[:, col]
        print(
            f"\n== {target}: {'the team scores' if target == 'team' else 'anyone scores'} again"
            f" by full time: train {y.mean():.1%} of {len(y):,} rows, test {y_test.mean():.1%}",
            flush=True,
        )
        print(f"{'model':18}{'skill':>8}{'log loss':>10}{'AUC':>7}{'calib':>7}  (cross-validation)")
        preds: dict[str, np.ndarray] = {}
        for spec in specs():
            start = time.monotonic()
            cv: list[Fold] = cross_validate(spec, train, y)
            chosen = min(cv, key=lambda f: f.scores.log_loss)
            p_cv = symmetric(chosen.p, opp_train) if target == "game" else chosen.p
            s = scores(y, p_cv)
            results["cv"].setdefault(target, {})[spec.name] = {"params": chosen.params, **asdict(s)}
            print(f"{line(spec.name, s)}  ({time.monotonic() - start:.0f}s)", flush=True)
            model = spec.make(chosen.params).fit(columns(train, spec.columns), y)
            p = model.predict_proba(columns(test, spec.columns))[:, 1]
            preds[spec.name] = symmetric(p, opp_test) if target == "game" else p
            if spec.name == SHIPPED:
                shipped[target] = model
        if target == "team":
            test_team = preds
        else:
            preds["from team"] = independent(test_team[SHIPPED], opp_test)
        print(f"Test: the 2022 World Cup ({len(np.unique(test.match_id))} matches)")
        for name, p in preds.items():
            s = scores(y_test, p)
            results["test"].setdefault(target, {})[name] = asdict(s)
            print(line(name, s))
        table = reliability(y_test, preds[SHIPPED])
        results["reliability"][target] = table
        print(
            f"Reliability ({SHIPPED}, test): "
            + "; ".join(f"{b} n={n} p={p:.0%} actual={a:.0%}" for b, n, p, a in table)
        )
        a = at_alerts(y_test, preds, alerting)
        results["at_alerts"][target] = asdict(a)
        print(
            f"At the goal model's alerts ({a.rows} rows): actual {a.actual:.1%}; predicted "
            + ", ".join(f"{n} {v:.1%}" for n, v in a.predicted.items())
        )

    doc = to_json(shipped, train, ls)
    model = FullTimeModel.from_json(doc)
    sample = raw["train"].x[:: max(1, len(train) // 2000)]
    every = (*FEATURE_NAMES, LEFT)
    x_live = with_left(
        Dataset(
            sample,
            np.zeros((len(sample), 2), bool),
            np.zeros(len(sample)),
            np.zeros(len(sample)),
            np.zeros(len(sample)),
        ),
        np.full(len(sample), model.end_min),
        model.end_residuals,
    )
    for target in TARGETS:
        ours = np.array([model.part(target).probability(model.values(r.tolist())) for r in sample])
        theirs = shipped[target].predict_proba(columns(x_live, every))[:, 1]
        gap = np.abs(ours - theirs).max()
        if gap > 1e-9:
            raise SystemExit(
                f"the engine's {target} probabilities differ from scikit-learn's by {gap:g}"
            )
    doc["test"] = {t: results["test"][t][SHIPPED] for t in TARGETS}
    args.out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    FullTimeModel.load(args.out)
    args.results.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {args.out} and {args.results}")


if __name__ == "__main__":
    main()
