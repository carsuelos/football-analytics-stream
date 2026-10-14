"""Train and evaluate the goal models: will a team score in the next few minutes?

    uv run python -m model.train                 # after make dataset; about 5 minutes

Models, from simplest to most flexible, each fitted on the training matches and
scored on the 2022 World Cup:

- base rate: the training rate, whatever is happening;
- game state: logistic regression on the minute and the score alone;
- logistic: logistic regression on every feature, standardized, L2-penalized;
- curved: the same, plus hinges that let the minute's effect bend (the chance
  of a goal in the next 10' falls off as full time nears);
- boosted: gradient-boosted trees (scikit-learn's HistGradientBoostingClassifier).

Hyperparameters are picked by cross-validation on the training set, with
folds grouped by match (rows of the same match are near-copies). The test set
is touched once, at the end. See docs/MODEL.md for what the numbers mean.
"""

import argparse
import itertools
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import rankdata
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from model.dataset import OUT, Dataset

GAME_STATE = ("minute", "extra_time", "score_diff", "goals_for", "goals_against", "since_goal_min")
FOLDS = 5
COOLDOWN_S = 300.0
BOOTSTRAP = 1000
SEED = 2022
PROBABILITY_BINS = (0.0, 0.05, 0.08, 0.11, 0.14, 0.18, 0.22, 0.27, 0.35, 1.0)
MINUTE_KNOTS = (60.0, 80.0, 85.0, 90.0, 95.0, 100.0)
"""Where the minute's effect may bend: max(0, minute - knot) for each."""
ALERTS_PER_MATCH = (14.2, 5.0, 2.0)
"""Operating points for alerts: the rules' volume (906 alerts in 64 matches),
then fewer, more selective ones."""


@dataclass(frozen=True)
class Scores:
    brier: float
    skill: float
    """Brier skill score against always predicting the evaluated set's own rate."""
    log_loss: float
    auc: float
    calibration: float
    """Predicted goals over actual goals."""


def scores(y: np.ndarray, p: np.ndarray) -> Scores:
    rate = float(y.mean())
    brier = float(brier_score_loss(y, p))
    return Scores(
        brier=brier,
        skill=1 - brier / (rate * (1 - rate)),
        log_loss=float(log_loss(y, p, labels=[False, True])),
        auc=float(roc_auc_score(y, p)) if 0 < rate < 1 else float("nan"),
        calibration=float(p.sum() / y.sum()),
    )


@dataclass(frozen=True)
class Spec:
    name: str
    columns: tuple[str, ...] | None
    """Feature columns; None for the base rate."""
    make: Callable[[dict[str, Any]], Any]
    grid: Sequence[dict[str, Any]]


class Hinges(BaseEstimator, TransformerMixin):  # type: ignore[misc]
    """Appends max(0, x[:, column] - knot) for each knot: with them a linear
    model's response to that column is a broken line instead of a straight one
    (a linear spline)."""

    def __init__(self, column: int, knots: Sequence[float]) -> None:
        self.column = column
        self.knots = knots

    def fit(self, _x: np.ndarray, _y: np.ndarray | None = None) -> "Hinges":
        return self

    def transform(self, x: np.ndarray) -> np.ndarray:
        col = x[:, self.column : self.column + 1]
        return np.hstack([x, *(np.maximum(0.0, col - k) for k in self.knots)])


def logistic(params: dict[str, Any], names: Sequence[str] = ()) -> Pipeline:
    """Standardized, L2-penalized logistic regression; with params["minute_knots"],
    hinges on the minute (which must be one of names) first."""
    steps: list[Any] = [StandardScaler(), LogisticRegression(C=params["C"], max_iter=3000)]
    if "minute_knots" in params:
        steps.insert(0, Hinges(list(names).index("minute"), params["minute_knots"]))
    return make_pipeline(*steps)


def boosted(params: dict[str, Any]) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        learning_rate=params["learning_rate"],
        max_iter=params["max_iter"],
        max_leaf_nodes=params["max_leaf_nodes"],
        min_samples_leaf=params["min_samples_leaf"],
        l2_regularization=1.0,
        early_stopping=False,
        random_state=SEED,
    )


class BaseRate:
    """Predicts the training rate for every row."""

    def fit(self, _x: np.ndarray, y: np.ndarray) -> "BaseRate":
        self.rate = float(y.mean())
        return self

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        return np.column_stack([np.full(len(x), 1 - self.rate), np.full(len(x), self.rate)])


def specs(names: Sequence[str]) -> list[Spec]:
    return [
        Spec("base rate", (), lambda _: BaseRate(), [{}]),
        Spec("game state", GAME_STATE, logistic, [{"C": 1.0}]),
        Spec("logistic", tuple(names), logistic, [{"C": c} for c in (0.001, 0.01, 1.0)]),
        Spec(
            "curved",
            tuple(names),
            lambda p: logistic(p, names),
            [{"C": c, "minute_knots": MINUTE_KNOTS} for c in (0.001, 0.01)],
        ),
        Spec(
            "boosted",
            tuple(names),
            boosted,
            [
                {
                    "learning_rate": 0.05,
                    "max_iter": n,
                    "max_leaf_nodes": leaves,
                    "min_samples_leaf": 500,
                }
                for n, leaves in ((100, 4), (150, 8), (300, 8))
            ],
        ),
    ]


def columns(d: Dataset, names: tuple[str, ...] | None) -> np.ndarray:
    if not names:
        return np.zeros((len(d), 1))
    return d.x[:, [d.names.index(n) for n in names]]


@dataclass(frozen=True)
class Fold:
    params: dict[str, Any]
    scores: Scores
    p: np.ndarray
    """Out-of-fold predictions: each row predicted by a model that did not see its match."""


def cross_validate(spec: Spec, train: Dataset, y: np.ndarray) -> list[Fold]:
    """Out-of-fold predictions and scores for each of spec's hyperparameters,
    folds grouped by match."""
    x = columns(train, spec.columns)
    results = []
    for params in spec.grid:
        p = np.zeros(len(y))
        for fit_idx, held_idx in GroupKFold(FOLDS).split(x, y, train.match_id):
            model = spec.make(params).fit(x[fit_idx], y[fit_idx])
            p[held_idx] = model.predict_proba(x[held_idx])[:, 1]
        results.append(Fold(params, scores(y, p), p))
    return results


@dataclass(frozen=True)
class AlertScores:
    alerts_per_match: float
    threshold: float
    alerts: int
    scores_5: float
    lift_5: float
    scores_10: float
    lift_10: float
    lift_5_interval: tuple[float, float]
    lift_10_interval: tuple[float, float]
    """95% intervals, resampling whole matches."""


def alerts(d: Dataset, p: np.ndarray, threshold: float) -> np.ndarray:
    """Rows where a model alert fires: p at or above threshold, at most once
    per team per COOLDOWN_S, like the detectors."""
    fired = np.zeros(len(d), dtype=bool)
    order = np.lexsort((d.play_s, d.team_id, d.match_id))
    last: dict[tuple[int, int], float] = {}
    for i in order:
        if p[i] < threshold:
            continue
        key = (int(d.match_id[i]), int(d.team_id[i]))
        if key in last and d.play_s[i] - last[key] < COOLDOWN_S:
            continue
        last[key] = float(d.play_s[i])
        fired[i] = True
    return fired


def threshold_for(d: Dataset, p: np.ndarray, per_match: float) -> float:
    """The threshold at which alerts fire about per_match times a match (by bisection)."""
    matches = len(np.unique(d.match_id))
    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = (lo + hi) / 2
        if alerts(d, p, mid).sum() / matches > per_match:
            lo = mid
        else:
            hi = mid
    return hi


def alert_scores(d: Dataset, p: np.ndarray, per_match: float, threshold: float) -> AlertScores:
    """How often the team scores after the alerts fired at threshold, and the
    lift: that over how often it scores after any row."""
    fired = alerts(d, p, threshold)
    ids, match_of = np.unique(d.match_id, return_inverse=True)

    def per_match_sums(v: np.ndarray) -> np.ndarray:
        return np.bincount(match_of, weights=v.astype(np.float64), minlength=len(ids))

    rows, n_fired = np.bincount(match_of, minlength=len(ids)), per_match_sums(fired)
    lifts: dict[int, tuple[float, float, tuple[float, float]]] = {}
    rng = np.random.default_rng(SEED)
    draws = rng.integers(0, len(ids), (BOOTSTRAP, len(ids)))
    for h in (5, 10):
        y = d.label(h)
        hits, goals = per_match_sums(y & fired), per_match_sums(y)
        rate = hits.sum() / n_fired.sum()
        with np.errstate(invalid="ignore", divide="ignore"):  # resamples without alerts
            boot = (hits[draws].sum(1) / n_fired[draws].sum(1)) / (
                goals[draws].sum(1) / rows[draws].sum(1)
            )
        lo, hi = np.nanpercentile(boot, [2.5, 97.5])
        lifts[h] = (float(rate), float(rate / y.mean()), (float(lo), float(hi)))
    return AlertScores(
        per_match,
        threshold,
        int(fired.sum()),
        lifts[5][0],
        lifts[5][1],
        lifts[10][0],
        lifts[10][1],
        lifts[5][2],
        lifts[10][2],
    )


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """ROC AUC by ranks (Mann-Whitney): roc_auc_score without sklearn's checks,
    which dominate when called thousands of times."""
    ranks = rankdata(p)
    pos = int(y.sum())
    neg = len(y) - pos
    return float((ranks[y].sum() - pos * (pos + 1) / 2) / (pos * neg))


def bootstrap(
    d: Dataset, y: np.ndarray, preds: dict[str, np.ndarray], reference: str
) -> dict[str, dict[str, tuple[float, float]]]:
    """95% intervals, resampling whole matches, for each model's Brier skill
    score, AUC, and Brier improvement over the reference model."""
    rng = np.random.default_rng(SEED)
    ids = np.unique(d.match_id)
    rows = {m: np.flatnonzero(d.match_id == m) for m in ids}
    samples: dict[str, dict[str, list[float]]] = {
        name: {"skill": [], "auc": [], "brier_gain": []} for name in preds
    }
    for _ in range(BOOTSTRAP):
        idx = np.concatenate([rows[m] for m in rng.choice(ids, len(ids))])
        yy = y[idx]
        rate = yy.mean()
        ref = float(np.mean((preds[reference][idx] - yy) ** 2))
        for name, p in preds.items():
            brier = float(np.mean((p[idx] - yy) ** 2))
            samples[name]["skill"].append(1 - brier / (rate * (1 - rate)))
            samples[name]["auc"].append(auc(yy, p[idx]))
            samples[name]["brier_gain"].append(1 - brier / ref)
    return {
        name: {
            k: (float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))) for k, v in s.items()
        }
        for name, s in samples.items()
    }


def reliability(y: np.ndarray, p: np.ndarray) -> list[tuple[str, int, float, float]]:
    """(probability bin, rows, mean prediction, actual rate) for each bin."""
    out = []
    for lo, hi in itertools.pairwise(PROBABILITY_BINS):
        m = (p >= lo) & (p < hi)
        if m.any():
            out.append((f"{lo:.0%}-{hi:.0%}", int(m.sum()), float(p[m].mean()), float(y[m].mean())))
    return out


def feature_names(model: Pipeline, names: Sequence[str]) -> list[str]:
    """The names of the columns the model's regression sees, hinges included."""
    hinges = [step for step in model if isinstance(step, Hinges)]
    extra = [f"{names[h.column]}>{k:g}" for h in hinges for k in h.knots]
    return [*names, *extra]


def minute_curve(model: Pipeline, names: Sequence[str]) -> list[tuple[float, float]]:
    """(minute, log-odds) of the minute's own contribution, from 15', with every
    other feature held still."""
    x = np.zeros((len(range(15, 125, 5)), len(names)))
    x[:, list(names).index("minute")] = np.arange(15, 125, 5)
    z = model[:-1].transform(x)
    i = [n == "minute" or n.startswith("minute>") for n in feature_names(model, names)]
    logit = z[:, i] @ model[-1].coef_[0][i]
    return [
        (float(m), float(v - logit[0])) for m, v in zip(x[:, i.index(True)], logit, strict=True)
    ]


def top_coefficients(model: Pipeline, names: Sequence[str], n: int = 12) -> list[tuple[str, float]]:
    names = feature_names(model, names)
    coef = model[-1].coef_[0]
    order = np.argsort(-np.abs(coef))[:n]
    return [(names[i], float(coef[i])) for i in order]


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--data", type=Path, default=OUT, metavar="DIR")
    parser.add_argument("--horizon", type=int, default=10, choices=(5, 10))
    parser.add_argument("--out", type=Path, default=OUT / "results.json", metavar="FILE")
    args = parser.parse_args()

    train, test = Dataset.load(args.data / "train.npz"), Dataset.load(args.data / "test.npz")
    y_train, y_test = train.label(args.horizon), test.label(args.horizon)
    print(
        f"Scoring within {args.horizon}': train {y_train.mean():.1%} of {len(train):,} rows, "
        f"test {y_test.mean():.1%} of {len(test):,}\n",
        flush=True,
    )
    results: dict[str, Any] = {"horizon_min": args.horizon, "cv": {}, "test": {}}
    test_preds: dict[str, np.ndarray] = {}
    fitted: dict[str, Any] = {}
    oof: dict[str, np.ndarray] = {}
    print(f"Cross-validation on the training set ({FOLDS} folds by match):")
    print(f"{'model':12}{'brier':>9}{'skill':>8}{'log loss':>10}{'AUC':>7}{'calib':>7}  params")
    for spec in specs(train.names):
        start = time.monotonic()
        cv = cross_validate(spec, train, y_train)
        for f in cv:
            s = f.scores
            print(
                f"{spec.name:12}{s.brier:9.5f}{s.skill:8.4f}{s.log_loss:10.4f}{s.auc:7.3f}"
                f"{s.calibration:7.2f}  {json.dumps(f.params)}",
                flush=True,
            )
        chosen = min(cv, key=lambda f: f.scores.log_loss)
        best, oof[spec.name] = chosen.params, chosen.p
        results["cv"][spec.name] = [{"params": f.params, **asdict(f.scores)} for f in cv]
        model = spec.make(best).fit(columns(train, spec.columns), y_train)
        fitted[spec.name] = model
        test_preds[spec.name] = model.predict_proba(columns(test, spec.columns))[:, 1]
        results["test"][spec.name] = {
            "params": best,
            **asdict(scores(y_test, test_preds[spec.name])),
        }
        print(f"  ({time.monotonic() - start:.0f}s; picked {json.dumps(best)})", flush=True)

    print(f"\nTest: the 2022 World Cup ({len(np.unique(test.match_id))} matches)")
    print(f"{'model':12}{'brier':>9}{'skill':>8}{'log loss':>10}{'AUC':>7}{'calib':>7}")
    for name, p in test_preds.items():
        s = scores(y_test, p)
        print(
            f"{name:12}{s.brier:9.5f}{s.skill:8.4f}{s.log_loss:10.4f}{s.auc:7.3f}{s.calibration:7.2f}"
        )

    print(f"\n95% intervals over {BOOTSTRAP} resamples of the test matches:")
    intervals = bootstrap(test, y_test, test_preds, "logistic")
    results["intervals"] = intervals
    print(f"{'model':12}{'skill':>18}{'AUC':>18}{'Brier gain on logistic':>26}")
    for name, iv in intervals.items():
        cells = "".join(f"{f'{lo:+.4f} to {hi:+.4f}':>18}" for lo, hi in (iv["skill"], iv["auc"]))
        lo, hi = iv["brier_gain"]
        print(f"{name:12}{cells}{f'{lo:+.4f} to {hi:+.4f}':>26}")

    print("\nReliability on the test set (rows by predicted probability):")
    results["reliability"] = {}
    for name in ("logistic", "curved", "boosted"):
        table = reliability(y_test, test_preds[name])
        results["reliability"][name] = table
        print(
            f"  {name}: " + "; ".join(f"{b} n={n} p={p:.1%} actual={a:.1%}" for b, n, p, a in table)
        )

    print(
        "\nAlerts: thresholds set on the training set's out-of-fold predictions for a number"
        " of alerts a match, 5' cooldown"
    )
    results["alerts"] = {}
    header = ("per match", "threshold", "alerts", "in 5", "lift", "in 10", "lift", "95%")
    widths = (10, 10, 8, 7, 6, 7, 6, 14)
    print(f"{'model':12}" + "".join(f"{h:>{w}}" for h, w in zip(header, widths, strict=True)))
    for name in ("game state", "logistic", "curved", "boosted"):
        results["alerts"][name] = []
        for per_match in ALERTS_PER_MATCH:
            t = threshold_for(train, oof[name], per_match)
            a = alert_scores(test, test_preds[name], per_match, t)
            results["alerts"][name].append(asdict(a))
            print(
                f"{name:12}{per_match:10.1f}{t:10.3f}{a.alerts:8d}{a.scores_5:7.1%}{a.lift_5:6.2f}"
                f"{a.scores_10:7.1%}{a.lift_10:6.2f}"
                f"{f'{a.lift_10_interval[0]:.2f}-{a.lift_10_interval[1]:.2f}':>14}"
            )

    print(
        "\nLogistic regression: the largest standardized coefficients"
        " (log-odds per standard deviation)"
    )
    results["coefficients"] = {}
    for name in ("logistic", "curved"):
        coefs = top_coefficients(fitted[name], train.names)
        results["coefficients"][name] = coefs
        print(f"  {name}: " + ", ".join(f"{n} {c:+.3f}" for n, c in coefs))
    curve = minute_curve(fitted["curved"], train.names)
    results["minute_curve"] = curve
    print("\nCurved: the minute's own effect on the log-odds, from 15'")
    print("  " + ", ".join(f"{m:.0f}' {v:+.2f}" for m, v in curve))

    print("\nBoosted trees: permutation importance on the test set (log loss increase)")
    x_test = columns(test, tuple(test.names))
    imp = permutation_importance(
        fitted["boosted"], x_test, y_test, scoring="neg_log_loss", n_repeats=5, random_state=SEED
    )
    order = np.argsort(-imp.importances_mean)[:12]
    results["importance"] = [(test.names[i], float(imp.importances_mean[i])) for i in order]
    for i in order:
        print(f"  {test.names[i]:20}{imp.importances_mean[i]:+.5f} ± {imp.importances_std[i]:.5f}")

    args.out.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
