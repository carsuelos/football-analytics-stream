from dataclasses import replace

import pytest

from engine.detectors import ControlShift, ControlShiftConfig, Signal
from engine.schema.common_schema import Team
from engine.schema.event_schema import MatchEvent
from tests.detector_specs import METRICS, build, recoveries, touch
from tests.factories import AWAY, HOME, tick_after

SWING = ControlShiftConfig(threshold=0.5, previous_max=-0.2)
"""Signals only on a swing, as before Phase 3 tuning turned the swing condition off."""


def swing(
    before: int,
    last: int,
    *,
    team: Team = HOME,
    other: Team = AWAY,
    window_s: int = 300,
    until_s: int | None = None,
) -> list[MatchEvent]:
    """`other` makes `before` recoveries in the window before last, then `team`
    makes `last` in the last window, which ends at until_s."""
    return build(
        touch(0, HOME),
        touch(5, AWAY),
        recoveries(other, before, window_s / 3),
        recoveries(team, last, window_s * 4 / 3),
        touch(until_s or 2 * window_s),
    )


def signals(events: list[MatchEvent], config: ControlShiftConfig | None = None) -> list[Signal]:
    return ControlShift(config or SWING).evaluate(tick_after(events, METRICS))


@pytest.mark.parametrize(("team", "other"), [(HOME, AWAY), (AWAY, HOME)])
def test_signals_when_a_pinned_back_team_takes_control(team: Team, other: Team) -> None:
    [s] = signals(swing(5, 10, team=team, other=other))
    # Balance: (10 - 0) / (10 + 0 + 5) now, from (0 - 5) / (0 + 5 + 5) before.
    assert (s.team_id, s.value, s.threshold, s.window_s) == (team.id, 10 / 15, 0.5, 300)
    assert s.features == {
        "balance": 10 / 15,
        "previous_balance": -0.5,
        "pressure_index": 10.0,
        "opponent_pressure_index": 0.0,
    }
    assert s.message == (
        f"{team.name} in control: pressure balance +0.67 over the last 5', from -0.50 the 5' before"
    )


@pytest.mark.parametrize(
    ("before", "last", "fires"), [(4, 16, True), (3, 16, False), (4, 15, False)]
)
def test_both_windows_must_reach_their_thresholds(before: int, last: int, fires: bool) -> None:
    # With smoothing 16, 4 against make -4 / 20 = -0.2 and 16 for make 16 / 32 = 0.5.
    config = replace(SWING, smoothing=16)
    assert [s.value for s in signals(swing(before, last), config)] == ([0.5] if fires else [])


@pytest.mark.parametrize(
    ("threshold", "previous_max", "fires"),
    [(0.6, -0.5, True), (0.7, -0.5, False), (0.6, -0.6, False)],
)
def test_the_thresholds_are_configurable(
    threshold: float, previous_max: float, fires: bool
) -> None:
    config = ControlShiftConfig(threshold=threshold, previous_max=previous_max)
    assert len(signals(swing(5, 10), config)) == fires  # balance 0.67, from -0.5


@pytest.mark.parametrize(("until_s", "fires"), [(600, True), (590, False)])
def test_needs_two_full_windows_of_play(until_s: int, fires: bool) -> None:
    assert len(signals(swing(5, 10, until_s=until_s))) == fires


def test_the_window_is_configurable() -> None:
    [s] = signals(swing(5, 10, window_s=120), replace(SWING, window_s=120))
    assert s.window_s == 120
    assert "over the last 2', from -0.50 the 2' before" in s.message


def test_by_default_dominance_is_enough_without_a_swing() -> None:
    # Home is on top in both windows: 20 / 25 = 0.8 before, 30 / 35 = 0.86 now.
    e = build(
        touch(0, HOME),
        touch(5, AWAY),
        recoveries(HOME, 20, 100),
        recoveries(HOME, 30, 400),
        touch(600),
    )
    [s] = ControlShift().evaluate(tick_after(e, METRICS))
    assert (s.team_id, s.threshold) == (HOME.id, 0.805)
    assert s.value == pytest.approx(30 / 35)
    assert s.features["previous_balance"] == pytest.approx(20 / 25)
