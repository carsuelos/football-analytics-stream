import itertools
from dataclasses import replace

import pytest

from engine.detectors import Detectors, Momentum, MomentumConfig
from engine.pipeline import Pipeline
from engine.schema.alert_schema import Alert, AlertType
from engine.schema.event_schema import EventType, MatchEvent
from engine.schema.feed_schema import FeedMessageKind as K
from engine.ticks import Ticker
from engine.windows import InMemoryStateStore
from tests.factories import AWAY, HOME, event, feed_event, feed_marker
from tests.test_detectors import METRICS

Z_SCORE = MomentumConfig(half_life_s=600, std_floor=3, threshold=2)
"""A low floor and the pre-tuning threshold, so the tests can work with true z-scores."""

OWN_HALF = (40.0, 40.0)
ATT_HALF = (65.0, 40.0)  # attacking half, short of the final third


def steady_match(
    until_s: int, *, surge_at: int | None = None, extra: int = 0, clumps: tuple[int, ...] = (5,)
) -> list[MatchEvent]:
    """A first half where Home's pressure index is steady.

    Home makes a clump of attacking-half recoveries (1 point each) just after
    every 5 minutes, so every 5' window ending on a tick holds exactly one
    clump. The clump sizes cycle through `clumps`. `extra` more recoveries come
    just before the tick at surge_at. Passes in each team's own half, every
    10s, keep the ticks on time and add no pressure.
    """
    timeline = [
        (float(s), (HOME, AWAY)[s // 10 % 2], EventType.pass_) for s in range(0, until_s, 10)
    ]
    sizes = itertools.cycle(clumps)
    for start in range(0, until_s, 300):
        timeline += [
            (start + 1 + j / 10, HOME, EventType.ball_recovery) for j in range(next(sizes))
        ]
    if surge_at is not None:
        timeline += [(surge_at - 9 + j / 10, HOME, EventType.ball_recovery) for j in range(extra)]
    timeline.sort(key=lambda t: t[0])
    return [
        event(
            1,
            clock,
            offset=i,
            team=team,
            type=type,
            location=ATT_HALF if type is EventType.ball_recovery else OWN_HALF,
        )
        for i, (clock, team, type) in enumerate(timeline)
    ]


def run(es: list[MatchEvent], momentum: Momentum | None = None) -> list[Alert]:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    d, t = Detectors([momentum or Momentum(Z_SCORE)]), Ticker(METRICS)
    msgs = [feed_marker(K.match_start, 0), *map(feed_event, es)]
    return [
        a
        for msg in msgs
        for item in p.handle(msg)
        if (tick := t.observe(p, item))
        for a in d.evaluate(tick)
    ]


@pytest.mark.parametrize("extra", [6, 5])
def test_signals_when_pressure_is_two_floored_deviations_above_normal(extra: int) -> None:
    # Normal is exactly 5 with no spread, so z = extra / std_floor (3.0).
    alerts = run(steady_match(1500, surge_at=1200, extra=extra))
    if extra == 5:
        assert alerts == []  # z 1.67
        return
    [alert] = alerts
    assert (alert.type, alert.team_id, alert.match_clock_s) == (AlertType.momentum_shift, 1, 1200)
    assert (alert.value, alert.threshold, alert.window_s) == (2.0, 2.0, 300)
    assert alert.features == {"pressure_index": 11.0, "baseline_mean": 5.0, "baseline_std": 0.0}
    assert (
        alert.message
        == "Home FC momentum: pressure 11.0 over the last 5', against a usual 5.0 (z +2.0)"
    )


@pytest.mark.parametrize(("surge_at", "fires"), [(900, True), (870, False)])
def test_no_signals_in_the_first_15_minutes(surge_at: int, fires: bool) -> None:
    alerts = run(steady_match(surge_at + 10, surge_at=surge_at, extra=10))
    assert clocks(alerts) == ([surge_at] if fires else [])


def test_z_uses_the_baseline_spread_when_it_is_above_the_floor() -> None:
    m = Momentum(replace(Z_SCORE, std_floor=0.5))
    [alert] = run(steady_match(1500, surge_at=1200, extra=8, clumps=(3, 7)), m)
    f = alert.features
    assert f["baseline_std"] > 0.5
    assert alert.value == pytest.approx(
        (f["pressure_index"] - f["baseline_mean"]) / f["baseline_std"]
    )


def test_the_window_is_configurable() -> None:
    m = Momentum(replace(Z_SCORE, window_s=60))
    [alert] = run(steady_match(1500, surge_at=1200, extra=10), m)
    assert (alert.match_clock_s, alert.window_s) == (1200, 60)
    assert alert.features["pressure_index"] == 10.0  # over 5' it would be 15
    assert "over the last 1'" in alert.message


def test_the_threshold_is_configurable() -> None:
    m = Momentum(replace(Z_SCORE, threshold=2.01))
    assert run(steady_match(1500, surge_at=1200, extra=6), m) == []  # z 2.0


def test_a_new_match_starts_the_baselines_over() -> None:
    m = Momentum(Z_SCORE)
    e = steady_match(1500, surge_at=1200, extra=10)
    assert clocks(run(e, m)) == [1200]
    # The same surge as the start of a new match: no baseline to compare with.
    later = [x for x in e if x.match_clock_s >= 1140]
    assert clocks(run(later, m)) == []


def clocks(alerts: list[Alert]) -> list[float]:
    return [a.match_clock_s for a in alerts]
