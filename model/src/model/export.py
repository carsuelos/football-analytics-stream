"""Export the goal model the engine runs: the curved logistic regression, as JSON.

    uv run python -m model.export      # after make dataset; about 30 seconds

Refits the model `make train` picked (docs/MODEL.md, step 3) on every training
match, sets its alert threshold for ALERTS_PER_MATCH on out-of-fold training
predictions, checks that the engine's plain-Python version gives the same
probabilities as scikit-learn, scores it on the World Cup, and writes
engine/src/engine/detectors/goal_model.json, which the engine loads by default.
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
from engine.detectors.goal_chance import DEFAULT_MODEL_PATH, GoalModel
from sklearn.pipeline import Pipeline

from model.dataset import OUT, WARMUP_S, Dataset
from model.train import (
    MINUTE_KNOTS,
    Spec,
    alert_scores,
    cross_validate,
    logistic,
    scores,
    threshold_for,
)

HORIZON_MIN = 10
PARAMS: dict[str, Any] = {"C": 0.01, "minute_knots": MINUTE_KNOTS}
ALERTS_PER_MATCH = 5.0
"""About one alert per team per half: selective enough to mean something
(10' lift 1.8 on the World Cup), frequent enough to see in a match."""


def to_json(
    model: Pipeline,
    names: tuple[str, ...],
    threshold: float,
    base_rate: float,
    meta: dict[str, str],
) -> dict[str, Any]:
    """The fitted pipeline (hinges, scaler, regression) as GoalModel's fields."""
    _, scaler, regression = model.named_steps.values()
    return {
        "model": "logistic regression with hinges on the minute (docs/MODEL.md, step 3)",
        "features": list(names),
        "minute_knots": list(model.steps[0][1].knots),
        "mean": scaler.mean_.tolist(),
        "scale": scaler.scale_.tolist(),
        "coef": regression.coef_[0].tolist(),
        "intercept": float(regression.intercept_[0]),
        "horizon_min": HORIZON_MIN,
        "threshold": threshold,
        "alerts_per_match": ALERTS_PER_MATCH,
        "base_rate": base_rate,
        "warmup_s": WARMUP_S,
        "xt_grid": meta.get("xt_grid", ""),
        "xt_grid_sha256": meta.get("xt_grid_sha256", ""),
    }


def engine_probabilities(model: GoalModel, x: np.ndarray) -> np.ndarray:
    return np.array([model.probability(row.tolist()) for row in x])


def export(train: Dataset, test: Dataset | None = None) -> tuple[dict[str, Any], GoalModel]:
    y = train.label(HORIZON_MIN)
    spec = Spec("curved", train.names, lambda p: logistic(p, train.names), [PARAMS])
    (fold,) = cross_validate(spec, train, y)
    threshold = threshold_for(train, fold.p, ALERTS_PER_MATCH)
    model = logistic(PARAMS, train.names).fit(train.x, y)
    doc = to_json(model, train.names, threshold, float(y.mean()), train.meta)
    doc["training"] = {
        "matches": len(np.unique(train.match_id)),
        "rows": len(train),
        "C": PARAMS["C"],
        "cv": asdict(fold.scores),
    }
    shipped = GoalModel(**_fields(doc), info={})

    sample = train.x[:: max(1, len(train) // 2000)]
    gap = np.abs(engine_probabilities(shipped, sample) - model.predict_proba(sample)[:, 1]).max()
    if gap > 1e-9:
        raise SystemExit(f"the engine's probabilities differ from scikit-learn's by {gap:g}")

    if test is not None:
        y_test = test.label(HORIZON_MIN)
        p = engine_probabilities(shipped, test.x)
        a = alert_scores(test, p, ALERTS_PER_MATCH, threshold)
        doc["test"] = {
            "matches": len(np.unique(test.match_id)),
            **asdict(scores(y_test, p)),
            "alerts": a.alerts,
            "lift_5": a.lift_5,
            "lift_10": a.lift_10,
        }
    return doc, shipped


def _fields(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "features": tuple(doc["features"]),
        "minute_knots": tuple(doc["minute_knots"]),
        "mean": tuple(doc["mean"]),
        "scale": tuple(doc["scale"]),
        "coef": tuple(doc["coef"]),
        "intercept": doc["intercept"],
        "horizon_min": doc["horizon_min"],
        "threshold": doc["threshold"],
        "base_rate": doc["base_rate"],
        "warmup_s": doc["warmup_s"],
        "xt_grid_sha256": doc["xt_grid_sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--data", type=Path, default=OUT, metavar="DIR")
    parser.add_argument("--out", type=Path, default=DEFAULT_MODEL_PATH, metavar="FILE")
    args = parser.parse_args()

    train = Dataset.load(args.data / "train.npz")
    test_path = args.data / "test.npz"
    test = Dataset.load(test_path) if test_path.exists() else None
    doc, _ = export(train, test)
    args.out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    GoalModel.load(args.out)
    print(
        f"threshold {doc['threshold']:.3f} for {ALERTS_PER_MATCH:g} alerts a match"
        f" (base rate {doc['base_rate']:.1%})"
    )
    if "test" in doc:
        t = doc["test"]
        print(
            f"World Cup: skill {t['skill']:.4f}, AUC {t['auc']:.3f}, calibration"
            f" {t['calibration']:.2f}; {t['alerts']} alerts, lift {t['lift_5']:.2f} in 5',"
            f" {t['lift_10']:.2f} in 10'"
        )
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
