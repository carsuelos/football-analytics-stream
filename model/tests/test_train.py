import json
import sys
from pathlib import Path

import numpy as np
import pytest
from engine.features import FEATURE_NAMES

from model.dataset import Dataset
from model.train import (
    COOLDOWN_S,
    Hinges,
    alert_scores,
    alerts,
    auc,
    logistic,
    main,
    minute_curve,
    scores,
    threshold_for,
)


def synthetic(matches: int, seed: int = 0) -> Dataset:
    """Ticks every 30s from 15' to 100' for two teams a match. Goals come more
    often to the team with more tilt, and stop near full time."""
    rng = np.random.default_rng(seed)
    play_s = np.arange(900.0, 6000.0, 30.0)
    rows = []
    for m in range(matches):
        for team in (1, 2):
            x = rng.normal(0.5, 0.1, (len(play_s), len(FEATURE_NAMES)))
            x[:, FEATURE_NAMES.index("minute")] = play_s / 60
            tilt = x[:, FEATURE_NAMES.index("tilt_match")]
            p = 1 / (1 + np.exp(-(-2.0 + 4 * (tilt - 0.5))))
            p[play_s > 85 * 60] *= 0.2
            y10 = rng.random(len(play_s)) < p
            y5 = y10 & (rng.random(len(play_s)) < 0.5)
            rows.append(
                Dataset(
                    x,
                    np.column_stack([y5, y10]),
                    np.full(len(play_s), m),
                    np.full(len(play_s), team),
                    play_s.copy(),
                )
            )
    return Dataset.concat(rows)


def one_team(p: list[float], step_s: float = 30.0) -> tuple[Dataset, np.ndarray]:
    n = len(p)
    d = Dataset(
        np.zeros((n, len(FEATURE_NAMES))),
        np.zeros((n, 2), dtype=bool),
        np.zeros(n, dtype=np.int64),
        np.ones(n, dtype=np.int64),
        np.arange(n) * step_s,
    )
    return d, np.array(p)


def test_scores() -> None:
    y = np.array([True, False, False, False])
    s = scores(y, np.array([0.25, 0.25, 0.25, 0.25]))
    assert s.brier == pytest.approx(0.1875)
    assert s.skill == pytest.approx(0.0)
    assert s.calibration == pytest.approx(1.0)
    assert scores(y, np.array([0.9, 0.1, 0.1, 0.1])).auc == 1.0


def test_auc_matches_sklearn_with_ties() -> None:
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(0)
    y = rng.random(500) < 0.2
    p = np.round(rng.random(500) + 0.3 * y, 1)  # few distinct values: many ties
    assert auc(y, p) == pytest.approx(roc_auc_score(y, p))


def test_alerts_respect_the_cooldown_per_team() -> None:
    d, p = one_team([0.5] * 25)  # 12 minutes over the threshold
    fired = alerts(d, p, 0.3)
    assert d.play_s[fired].tolist() == [0.0, COOLDOWN_S, 2 * COOLDOWN_S]


def test_alerts_need_the_threshold() -> None:
    d, p = one_team([0.1, 0.4, 0.1, 0.4])
    assert alerts(d, p, 0.4).tolist() == [False, True, False, False]  # 60s later: cooling down


def test_threshold_for_hits_the_alert_rate() -> None:
    d = synthetic(4)
    p = np.random.default_rng(1).random(len(d))
    t = threshold_for(d, p, 3.0)
    assert alerts(d, p, t).sum() / 4 <= 3.0 < alerts(d, p, t - 0.01).sum() / 4


def test_alert_scores_lift() -> None:
    d = synthetic(6)
    y = d.label(10)
    a = alert_scores(d, y.astype(float), 2.0, 0.5)  # alerts exactly when a goal is coming
    assert a.scores_10 == 1.0
    assert a.lift_10 == pytest.approx(1 / y.mean())
    lo, hi = a.lift_10_interval
    assert lo <= a.lift_10 <= hi


def test_hinges_bend_a_column() -> None:
    x = np.array([[50.0, 1.0], [70.0, 1.0], [95.0, 1.0]])
    out = Hinges(0, (60.0, 90.0)).fit_transform(x)
    assert out[:, 2:].tolist() == [[0.0, 0.0], [10.0, 0.0], [35.0, 5.0]]


def test_curved_logistic_learns_the_drop_at_full_time() -> None:
    d = synthetic(20)
    model = logistic({"C": 1.0, "minute_knots": (80.0, 85.0, 90.0)}, d.names)
    model.fit(d.x, d.label(10))
    curve = dict(minute_curve(model, d.names))
    assert curve[95.0] < curve[80.0] - 0.5


def test_main_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    synthetic(10, seed=0).save(tmp_path / "train.npz")
    synthetic(5, seed=1).save(tmp_path / "test.npz")
    out = tmp_path / "results.json"
    monkeypatch.setattr(sys, "argv", ["train", "--data", str(tmp_path), "--out", str(out)])
    main()
    results = json.loads(out.read_text())
    assert set(results["test"]) == {"base rate", "game state", "logistic", "curved", "boosted"}
    assert results["test"]["logistic"]["auc"] > 0.6  # tilt_match carries the signal
    assert results["coefficients"]["logistic"][0][0] == "tilt_match"
