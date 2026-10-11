import pytest

from engine.metrics import MetricsConfig, PressureWeights, XTGrid, snapshot
from engine.schema.common_schema import Team
from engine.schema.event_schema import EventOutcome, EventType, MatchEvent
from engine.windows import InMemoryStateStore, SlidingWindows
from tests.factories import AWAY, HOME, event, timed

IDS = (HOME.id, AWAY.id)
# Column c is worth c / 10 (every row the same), so a move of one column adds 0.1.
GRID = XTGrid.from_lists([[c / 10 for c in range(12)] for _ in range(8)])
CONFIG = MetricsConfig(GRID)


def windows_after(events: list[MatchEvent]) -> SlidingWindows:
    w = SlidingWindows(InMemoryStateStore(), match_id=7)
    for item in timed(events):
        w.add(item)
    return w


def forward_pass(clock_s: float, *, team: Team = HOME, offset: int | None = None) -> MatchEvent:
    return event(
        1,
        clock_s,
        team=team,
        offset=offset,
        match_id=7,
        location=(85, 40),
        end_location=(105, 40),  # two columns on, into the box
        outcome=EventOutcome.success,
    )


def test_nothing_before_the_first_event() -> None:
    assert snapshot(windows_after([]), 300, IDS, CONFIG) is None


def test_snapshot_describes_the_window_ending_at_the_latest_event() -> None:
    events = [
        forward_pass(0, offset=10),
        forward_pass(60, offset=11),
        forward_pass(90, team=AWAY, offset=12),
        event(1, 120, offset=13, match_id=7, type=EventType.pressure, team=AWAY),
    ]
    snap = snapshot(windows_after(events), 300, IDS, CONFIG)
    assert snap is not None
    assert (snap.match_id, snap.offset, snap.period, snap.match_clock_s) == (7, 13, 1, 120)
    assert snap.window_s == 300
    home, away = snap.teams
    assert (home.team_id, away.team_id) == IDS
    assert home.field_tilt == pytest.approx(2 / 3)
    assert away.field_tilt == pytest.approx(1 / 3)
    assert home.xt_added == pytest.approx(0.4)
    # 2 minutes of play covered so far, not the window's 5.
    assert home.xt_velocity == pytest.approx(0.2)
    assert away.xt_velocity == pytest.approx(0.1)
    # Box entries at 1.5 each.
    assert (home.pressure_index, away.pressure_index) == (3.0, 1.5)


def test_snapshot_uses_only_the_window_and_the_given_weights() -> None:
    events = [forward_pass(0), forward_pass(400), forward_pass(500)]
    config = MetricsConfig(GRID, PressureWeights(box_entries=10))
    snap = snapshot(windows_after(events), 300, IDS, config)
    assert snap is not None
    home = snap.teams[0]
    assert home.xt_added == pytest.approx(0.4)  # the pass at 0:00 is out of the window
    assert home.xt_velocity == pytest.approx(0.08)  # over the full 5 minutes
    assert home.pressure_index == 20


def test_teams_come_in_the_order_given() -> None:
    snap = snapshot(windows_after([forward_pass(0)]), 300, (AWAY.id, HOME.id), CONFIG)
    assert snap is not None
    assert [t.team_id for t in snap.teams] == [AWAY.id, HOME.id]
    assert [t.field_tilt for t in snap.teams] == [0, 1]
