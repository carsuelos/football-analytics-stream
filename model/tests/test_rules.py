import json
import math
import random
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from engine.detectors import ControlShiftConfig, GoalThreatConfig, MomentumConfig
from engine.metrics import PressureWeights
from engine.schema.event_schema import EventType, MatchEvent, ShotDetail, ShotOutcome

from model.rules import (
    COMPONENTS,
    COOLDOWN_S,
    PHASE_2_RULES,
    RuleInputs,
    Rules,
    control_shift_scores,
    fire,
    match_inputs,
    threshold_for,
)
from tests.test_dataset import AWAY, HOME, ev, write_feed


def busy_match(seed: int = 1) -> list[MatchEvent]:
    """45' of passes with spells of pressure, shots and three goals."""
    rng = random.Random(seed)
    events: list[MatchEvent] = []
    for clock_s in range(0, 2700, 5):
        n = len(events)
        team = (HOME, AWAY)[(clock_s // 400) % 2] if rng.random() < 0.7 else (HOME, AWAY)[n % 2]
        r = rng.random()
        if r < 0.15:
            events.append(ev(n, clock_s, team, type=EventType.ball_recovery, location=[85, 40]))
        elif r < 0.25:
            events.append(ev(n, clock_s, team, location=[90, 40], end_location=[108, 40]))
        elif r < 0.29:
            goal = clock_s in (1300, 1800, 2200) or rng.random() < 0.02
            outcome = ShotOutcome.goal if goal else ShotOutcome.saved
            shot = ShotDetail(xg=rng.uniform(0.02, 0.5), outcome=outcome)
            events.append(
                ev(
                    n,
                    clock_s,
                    team,
                    type=EventType.shot,
                    location=[110, 40],
                    end_location=None,
                    outcome=None,
                    shot=shot,
                )
            )
        else:
            events.append(ev(n, clock_s, team))
    return events


def write_grid(path: Path) -> Path:
    path.write_text(json.dumps([[0.01 * c for c in range(12)]] * 8))
    return path


def test_the_simulation_raises_exactly_the_engines_alerts(tmp_path: Path) -> None:
    feed, grid = tmp_path / "7.jsonl", write_grid(tmp_path / "grid.json")
    write_feed(feed, busy_match())
    # Low thresholds, so every rule fires several times despite the cooldown.
    rules = Rules(
        PressureWeights(),
        MomentumConfig(std_floor=1.0, threshold=0.5),
        GoalThreatConfig(threshold=0.1),
        ControlShiftConfig(threshold=0.2, previous_max=0.3),
    )
    simulated = rules.alerts(match_inputs(feed, grid))
    assert {name for name, *_ in simulated} == {"momentum_shift", "goal_threat", "control_shift"}
    assert len(simulated) > 10
    assert simulated == rules.engine_alerts(feed, grid)

    phase_2 = PHASE_2_RULES.alerts(match_inputs(feed, grid))
    assert phase_2 == PHASE_2_RULES.engine_alerts(feed, grid)


def inputs(
    play_s: list[float], team_id: list[int], match_id: list[int] | None = None
) -> RuleInputs:
    n, k = len(play_s), len(COMPONENTS)
    return RuleInputs(
        match_id=np.array(match_id or [7] * n),
        team_id=np.array(team_id),
        play_s=np.array(play_s, dtype=np.float64),
        own=np.zeros((n, k)),
        opp=np.zeros((n, k)),
        own_prev=np.zeros((n, k)),
        opp_prev=np.zeros((n, k)),
        own_since_goal=np.zeros((n, k)),
        xt_since_goal=np.zeros(n),
        covered_since_goal=np.zeros(n),
        y=np.zeros((n, 2), dtype=bool),
        goals=np.zeros((0, 3)),
    )


def test_fire_keeps_a_cooldown_per_team() -> None:
    d = inputs([0, 0, 60, COOLDOWN_S - 1, COOLDOWN_S, COOLDOWN_S], [1, 2, 1, 1, 1, 2])
    score = np.array([1.0, 1.0, 1.0, 1.0, 1.0, math.nan])
    assert fire(d, score, 0.5).tolist() == [True, True, False, False, True, False]
    assert not fire(d, score, 1.5).any()


def test_threshold_for_hits_the_alerts_per_match() -> None:
    # Two matches, one team, a tick a cooldown apart so the cooldown never bites.
    play_s = [i * COOLDOWN_S for i in range(10)] * 2
    d = inputs(play_s, [1] * 20, [1] * 10 + [2] * 10)
    score = np.arange(20, dtype=np.float64)
    t = threshold_for(d, score, 3)
    assert fire(d, score, t).sum() == 6
    assert 13 < t < 13.001  # just above 13: the lowest threshold that fires only 14 to 19


def test_control_shift_needs_the_window_before_at_most_previous_max() -> None:
    d = inputs([600, 600, 600], [1, 1, 1])
    recoveries = COMPONENTS.index("recoveries")
    d.own[:, recoveries] = 10
    d.opp_prev[0, recoveries] = 5  # pinned back before: -5 / 10
    d.own_prev[1, recoveries] = 5  # on top before: +5 / 10
    d.own_prev[2] = math.nan  # not 10' of play yet
    c = ControlShiftConfig(smoothing=5.0, previous_max=-0.2)
    score = control_shift_scores(d, c, PressureWeights())
    assert score[0] == pytest.approx(10 / 15)
    assert np.isnan(score[1:]).all()
    off = control_shift_scores(d, replace(c, previous_max=1.0), PressureWeights())
    assert off[:2] == pytest.approx([10 / 15, 10 / 15])
    assert np.isnan(off[2])


def test_save_load_and_subset(tmp_path: Path) -> None:
    d = inputs([0, 30, 0], [1, 1, 2], [7, 7, 8])
    d = replace(d, goals=np.array([[7, 1, 30.0], [8, 2, 10.0]]))
    d.own[1, 0] = 3
    d.save(tmp_path / "rules.npz", xt_grid="grid.json")
    back = RuleInputs.load(tmp_path / "rules.npz")
    assert back.meta == {"xt_grid": "grid.json"}
    assert back.own.tolist() == d.own.tolist()
    assert back.series().tolist() == [0, 0, 1]
    seven = back.subset([7])
    assert (len(seven), seven.matches(), seven.goals.tolist()) == (2, 1, [[7, 1, 30.0]])
