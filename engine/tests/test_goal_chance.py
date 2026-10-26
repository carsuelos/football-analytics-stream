import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from engine.backtest import replay
from engine.detectors import (
    DEFAULT_MODEL_PATH,
    Detectors,
    GoalChance,
    GoalModel,
    GoalModelError,
    default_detectors,
)
from engine.detectors.goal_chance import describe, grid_digest, grid_mismatch
from engine.features import FEATURE_NAMES
from engine.schema.alert_schema import AlertType
from engine.schema.event_schema import ShotOutcome
from tests.factories import AWAY, HOME
from tests.test_features import METRICS, a_match, shot

F = {name: i for i, name in enumerate(FEATURE_NAMES)}


def model(
    coef: dict[str, float] | None = None, knots: tuple[float, ...] = (), **kw: Any
) -> GoalModel:
    """A model on raw features (mean 0, scale 1) with the given coefficients."""
    terms = (*FEATURE_NAMES, *(f"minute>{k:g}" for k in knots))
    n = len(terms)
    weights = coef or {}
    fields: dict[str, Any] = {
        "features": FEATURE_NAMES,
        "minute_knots": knots,
        "mean": (0.0,) * n,
        "scale": (1.0,) * n,
        "coef": tuple(weights.get(t, 0.0) for t in terms),
        "intercept": -2.0,
        "horizon_min": 10,
        "threshold": 0.5,
        "base_rate": 0.13,
        "warmup_s": 900.0,
        "xt_grid_sha256": "abc",
        "info": {},
    }
    return GoalModel(**(fields | kw))


def test_the_shipped_model_loads() -> None:
    m = GoalModel.load()
    assert m.features == FEATURE_NAMES
    assert m.horizon_min == 10 and m.warmup_s == 900
    assert 0.1 < m.base_rate < m.threshold < 0.5
    assert len(m.xt_grid_sha256) == 12
    # Average rows get about the base rate; the clock at 95' pushes it right down.
    average = list(m.mean[: len(FEATURE_NAMES)])
    assert m.probability(average) == pytest.approx(m.base_rate, abs=0.03)
    late = average.copy()
    late[F["minute"]] = 97.0
    assert m.probability(late) < m.base_rate / 2


def test_probability_is_a_logistic_regression_with_hinges() -> None:
    m = model({"minute": 0.01, "tilt_match": 2.0, "minute>80": -0.5}, knots=(80.0,))
    m = replace(m, mean=tuple(0.5 if t == "tilt_match" else 0.0 for t in m.terms))
    x = [0.0] * len(FEATURE_NAMES)
    x[F["minute"]], x[F["tilt_match"]] = 90.0, 0.7
    logit = -2.0 + 0.01 * 90 + 2.0 * (0.7 - 0.5) - 0.5 * (90 - 80)
    assert m.probability(x) == pytest.approx(1 / (1 + math.exp(-logit)))
    x[F["minute"]] = 70.0  # before the knot, the hinge adds nothing
    logit = -2.0 + 0.01 * 70 + 2.0 * 0.2
    assert m.probability(x) == pytest.approx(1 / (1 + math.exp(-logit)))
    assert m.terms[-1] == "minute>80"


def test_bad_models_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(GoalModelError, match="different features"):
        model(features=FEATURE_NAMES[:-1])
    with pytest.raises(GoalModelError, match="coefficients"):
        model(mean=(0.0,))
    with pytest.raises(GoalModelError, match="positive"):
        model(scale=(0.0,) * len(FEATURE_NAMES))
    with pytest.raises(GoalModelError, match="no goal model"):
        GoalModel.load(tmp_path / "missing.json")
    (tmp_path / "bad.json").write_text("{}")
    with pytest.raises(GoalModelError, match="cannot read"):
        GoalModel.load(tmp_path / "bad.json")


def test_a_model_round_trips_through_json(tmp_path: Path) -> None:
    doc = json.loads(DEFAULT_MODEL_PATH.read_text())
    doc["note"] = "kept"
    path = tmp_path / "m.json"
    path.write_text(json.dumps(doc))
    m = GoalModel.load(path)
    assert m.coef == tuple(doc["coef"])
    assert m.info["note"] == "kept"


def test_it_alerts_after_the_warm_up_with_the_reasons() -> None:
    # HOME has about two thirds of the final-third touches, so tilt_match is
    # about 0.65: sigmoid(-2 + 4 * 0.65) = 0.65 for HOME, 0.35 for AWAY.
    detectors = Detectors([GoalChance(model({"tilt_match": 4.0}))])
    r = replay(a_match(), METRICS, detectors=detectors)
    assert {a.alert.team_id for a in r.alerts} == {HOME.id}
    assert [round(a.play_s) for a in r.alerts] == [900, 1200, 1500]  # 5' cooldown
    alert = r.alerts[0].alert
    assert alert.type is AlertType.goal_chance
    tilt = alert.features["tilt_match"]
    assert tilt == pytest.approx(0.65, abs=0.02)
    assert alert.value == pytest.approx(1 / (1 + math.exp(2 - 4 * tilt)))
    assert (alert.threshold, alert.window_s) == (0.5, 600)
    assert set(alert.features) == {"base_rate", "tilt_match"}
    assert alert.message == (
        f"Home FC: {alert.value:.0%} chance to score in the next 10' (usually 13%):"
        " high field tilt (match)"
    )


def test_a_threshold_can_be_overridden() -> None:
    detectors = Detectors([GoalChance(model({"tilt_match": 4.0}), threshold=0.3)])
    r = replay(a_match(), METRICS, detectors=detectors)
    assert {a.alert.team_id for a in r.alerts} == {HOME.id, AWAY.id}


def test_the_clock_and_score_are_not_reported_as_reasons() -> None:
    detectors = Detectors([GoalChance(model({"minute": 0.2}))])  # -2 + 0.2 * 15 = 1
    r = replay(a_match(), METRICS, detectors=detectors)
    assert r.alerts
    alert = r.alerts[0].alert
    assert set(alert.features) == {"base_rate"}
    assert alert.message.endswith("(usually 13%)")


def test_default_detectors() -> None:
    assert [d.type for d in default_detectors().detectors] == [
        AlertType.momentum_shift,
        AlertType.goal_threat,
        AlertType.control_shift,
    ]
    assert default_detectors(model()).detectors[-1].type is AlertType.goal_chance


def test_describe() -> None:
    assert describe("tilt_match") == "field tilt (match)"
    assert describe("opp_pressure_10") == "opponent's pressure (last 10')"
    assert describe("box_entries_5") == "box entries (last 5')"
    assert describe("since_goal_min") == "time since the last goal"
    assert len({describe(n) for n in FEATURE_NAMES}) == len(FEATURE_NAMES)


def test_grid_mismatch(tmp_path: Path) -> None:
    grid = tmp_path / "grid.json"
    grid.write_text("[]")
    assert grid_mismatch(model(xt_grid_sha256=grid_digest(grid)), grid) is None
    assert "different xT grid" in (grid_mismatch(model(), grid) or "")
    assert grid_mismatch(model(), tmp_path / "missing.json") is None


def test_no_alert_within_a_minute_of_a_goal() -> None:
    # HOME scores at 24:50: the 25' check would alert on the goal itself, so the
    # alert waits until the first check a minute after it (events here come
    # every 20s, so 26:00).
    detectors = Detectors([GoalChance(model({"tilt_match": 4.0}))])
    r = replay(a_match([shot(1490, ShotOutcome.goal)]), METRICS, detectors=detectors)
    assert [round(a.play_s) for a in r.alerts] == [900, 1200, 1560]
