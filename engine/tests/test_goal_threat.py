import pytest

from engine.detectors import GoalThreat, GoalThreatConfig, Signal
from engine.schema.event_schema import EventType, MatchEvent, ShotOutcome
from tests.detector_specs import METRICS, build, progression, recoveries, shot, touch
from tests.factories import AWAY, HOME, tick_after

EVERY_TICK = GoalThreatConfig(threshold=0.0)
"""Signals for both teams on every tick, to show the features."""


def signals(events: list[MatchEvent], config: GoalThreatConfig | None = None) -> list[Signal]:
    return GoalThreat(config).evaluate(tick_after(events, METRICS))


def features(events: list[MatchEvent]) -> dict[int, dict[str, float]]:
    return {s.team_id: s.features for s in signals(events, EVERY_TICK)}


def test_a_team_at_both_scales_is_exactly_at_the_threshold() -> None:
    # -3 + 1.5 * 18 / 18 + 1.5 * 0.05 / 0.05 = 0, and sigmoid(0) = 0.5.
    e = build(touch(0), progression(1, HOME, 5), recoveries(HOME, 18, 10), touch(60))
    [s] = signals(e)
    assert (s.team_id, s.threshold, s.window_s) == (HOME.id, 0.5, 300)
    assert s.value == pytest.approx(0.5)
    assert s.features == {"pressure_index": 18.0, "xt_velocity": 0.05, "covered_s": 60.0}
    assert s.message == "Home FC goal threat 50%: pressure 18.0, xT +0.050/min over the last 1'"


@pytest.mark.parametrize(("pressure", "fires"), [(4, True), (3, False)])
def test_the_score_weighs_and_scales_each_feature(pressure: int, fires: bool) -> None:
    # -4 + 1 * 4 / 2 + 2 * 0.11 / 0.11 = 0, so 4 recoveries are exactly enough.
    config = GoalThreatConfig(
        bias=-4, pressure_weight=1, pressure_scale=2, xt_weight=2, xt_scale=0.11, threshold=0.5
    )
    e = build(touch(0), progression(1, HOME, 11), recoveries(HOME, pressure, 10), touch(60))
    assert [s.value for s in signals(e, config)] == ([0.5] if fires else [])


def test_xt_velocity_is_per_minute_of_play_covered() -> None:
    e = build(touch(0), progression(1, HOME, 6), touch(240))
    home = features(e)[HOME.id]
    assert home["covered_s"] == 240.0
    assert home["xt_velocity"] == pytest.approx(0.06 / 4)


def test_only_play_since_the_last_goal_in_the_window_counts() -> None:
    e = build(
        touch(0),
        recoveries(HOME, 10, 10),
        shot(50, HOME, ShotOutcome.goal),
        recoveries(HOME, 10, 60),
        progression(80, HOME, 5),
        shot(100, AWAY, ShotOutcome.goal),
        recoveries(HOME, 2, 110),
        shot(130, HOME, ShotOutcome.saved),  # a shot, but not a goal: 2 * (1 + 0.25)
        touch(160),
    )
    f = features(e)
    assert f[HOME.id] == {"pressure_index": 4.5, "xt_velocity": 0.0, "covered_s": 60.0}
    assert f[AWAY.id]["pressure_index"] == 0.0  # its goal is where the count starts


def test_an_own_goal_also_starts_the_count_again() -> None:
    own_goal = {"type": EventType.own_goal, "location": (5.0, 40.0)}
    e = build(
        touch(0),
        recoveries(HOME, 10, 10),
        (50, AWAY, own_goal),  # Away put it into their own net: a goal for Home
        recoveries(HOME, 2, 60),
        touch(110),
    )
    assert features(e)[HOME.id] == {"pressure_index": 2.0, "xt_velocity": 0.0, "covered_s": 60.0}


def test_a_goal_before_the_window_does_not_matter() -> None:
    e = build(shot(0, HOME, ShotOutcome.goal), touch(10), recoveries(HOME, 3, 200), touch(400))
    assert features(e)[HOME.id] == {"pressure_index": 3.0, "xt_velocity": 0.0, "covered_s": 300.0}


def test_the_window_is_configurable() -> None:
    e = build(touch(0), recoveries(HOME, 3, 10), recoveries(HOME, 2, 250), touch(300))
    config = GoalThreatConfig(window_s=60, threshold=0)
    [home] = [s for s in signals(e, config) if s.team_id == HOME.id]
    assert home.window_s == 60
    assert home.features == {"pressure_index": 2.0, "xt_velocity": 0.0, "covered_s": 60.0}
