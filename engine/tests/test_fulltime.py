import json
import math
from pathlib import Path
from typing import Any

import pytest

from engine.backtest import replay
from engine.detectors import (
    DEFAULT_FULLTIME_PATH,
    Detectors,
    FullTimeModel,
    FullTimeModelError,
    GoalChance,
    default_detectors,
)
from engine.detectors.fulltime import MIN_LEFT, minutes_left
from engine.features import FEATURE_NAMES
from tests.factories import HOME
from tests.test_features import METRICS, a_match
from tests.test_goal_chance import model as goal_model

N = len(FEATURE_NAMES) + 1 + 2  # the features, the minutes left, two knots


def part(coef: dict[int, float], intercept: float = 0.0) -> dict[str, Any]:
    return {
        "mean": [0.0] * N,
        "scale": [1.0] * N,
        "coef": [coef.get(i, 0.0) for i in range(N)],
        "intercept": intercept,
        "base_rate": 0.4,
    }


def doc(**kw: Any) -> dict[str, Any]:
    left = len(FEATURE_NAMES)
    return {
        "features": list(FEATURE_NAMES),
        "left_knots": [5.0, 20.0],
        "end_min": 100.0,
        "end_residuals": [-2.0, 0.0, 2.0],
        # The team's chance: sigmoid(0.05 * minutes left - 1); the game's: sigmoid(goals_for).
        "team": part({left: 0.05}, -1.0),
        "game": part({FEATURE_NAMES.index("goals_for"): 1.0}),
        "warmup_s": 900.0,
        "xt_grid_sha256": "abc",
        "note": "kept",
    } | kw


def test_minutes_left_is_the_expected_time_to_an_end_still_ahead() -> None:
    # Ends at 98, 100 and 102.
    assert minutes_left(60.0, 100.0, (-2.0, 0.0, 2.0)) == pytest.approx(40.0)
    assert minutes_left(99.0, 100.0, (-2.0, 0.0, 2.0)) == pytest.approx(2.0)  # 100 or 102
    assert minutes_left(103.0, 100.0, (-2.0, 0.0, 2.0)) == MIN_LEFT


def test_it_predicts_each_team_and_the_game_the_same_for_both() -> None:
    m = FullTimeModel.from_json(doc())
    x = [0.0] * len(FEATURE_NAMES)
    x[FEATURE_NAMES.index("minute")] = 60.0
    home, away = list(x), list(x)
    home[FEATURE_NAMES.index("goals_for")] = 2.0
    out = m.predict({1: home, 2: away})
    left = 40.0
    team = 1 / (1 + math.exp(-(0.05 * left - 1)))
    assert out[1].team == pytest.approx(team) and out[2].team == pytest.approx(team)
    game = (1 / (1 + math.exp(-2.0)) + 0.5) / 2
    assert out[1].game == pytest.approx(game) and out[2].game == pytest.approx(game)
    assert m.info == {"note": "kept"}


def test_it_rejects_a_model_for_other_features(tmp_path: Path) -> None:
    with pytest.raises(FullTimeModelError, match="different features"):
        FullTimeModel.from_json(doc(features=["minute"]))
    with pytest.raises(FullTimeModelError, match="no full-time model"):
        FullTimeModel.load(tmp_path / "missing.json")
    (tmp_path / "bad.json").write_text("{}")
    with pytest.raises(FullTimeModelError, match="cannot read"):
        FullTimeModel.load(tmp_path / "bad.json")


def test_the_shipped_model_loads_and_is_sensible() -> None:
    m = FullTimeModel.load(DEFAULT_FULLTIME_PATH)
    assert 95 < m.end_min < 105
    x = [0.0] * len(FEATURE_NAMES)
    early, late = list(x), list(x)
    early[FEATURE_NAMES.index("minute")] = 20.0
    late[FEATURE_NAMES.index("minute")] = 95.0
    a, b = m.predict({1: early, 2: early})[1], m.predict({1: late, 2: late})[1]
    assert b.team < a.team < a.game
    assert json.loads(DEFAULT_FULLTIME_PATH.read_text())["test"]["team"]["auc"] > 0.6


def test_goal_chance_alerts_say_what_the_next_lines_are_worth() -> None:
    ft = FullTimeModel.from_json(doc())
    detectors = Detectors([GoalChance(goal_model({"tilt_match": 4.0}), fulltime=ft)])
    alert = replay(a_match(), METRICS, detectors=detectors).alerts[0].alert
    assert alert.team_id == HOME.id
    f = alert.features
    assert 0 < f["ft_team"] < 1 and 0 < f["ft_game"] < 1
    assert (f["team_line"], f["game_line"]) == (1.5, 1.5)  # Home FC 1-0 up
    assert alert.message.endswith(
        f". By full time: {f['ft_team']:.0%} to score again (Home FC over 1.5),"
        f" {f['ft_game']:.0%} for any goal (over 1.5)"
    )


def test_the_default_detectors_use_the_shipped_model() -> None:
    goal = next(d for d in default_detectors(goal_model({})).detectors if isinstance(d, GoalChance))
    assert goal.fulltime is not None
