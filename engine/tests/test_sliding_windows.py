import math

import pytest

from engine.clock import MatchTime
from engine.schema.event_schema import MatchEvent
from engine.windows import InMemoryStateStore, SlidingWindows, WindowMode
from tests.factories import event, timed

FIVE, TEN = 300.0, 600.0


def windows_after(
    events: list[MatchEvent], mode: WindowMode = WindowMode.CONTINUOUS
) -> SlidingWindows:
    w = SlidingWindows(InMemoryStateStore(), match_id=1, mode=mode)
    for item in timed(events):
        w.add(item)
    return w


def clocks(w: SlidingWindows, length_s: float) -> list[tuple[int, float]]:
    return [(i.event.period, i.event.match_clock_s) for i in w.events(length_s)]


def test_empty_before_the_first_event() -> None:
    w = windows_after([])
    assert w.now is None
    assert w.events(FIVE) == []


def test_windows_hold_the_last_n_seconds_of_play() -> None:
    w = windows_after([event(1, s) for s in (0, 100, 299, 300, 301, 600, 601, 900)])
    assert w.now == MatchTime(1, 900)
    assert clocks(w, FIVE) == [(1, 601), (1, 900)]  # 600 is exactly 5 minutes back: excluded
    assert clocks(w, TEN) == [(1, 301), (1, 600), (1, 601), (1, 900)]


def test_continuous_mode_runs_across_half_time() -> None:
    # 1st half ends at 52:34 (3154s); the 2nd starts at 45:00 (2700s) on the clock.
    w = windows_after(
        [event(1, 2700), event(1, 3000), event(1, 3154), event(2, 2700), event(2, 2760)]
    )
    # Play time starts at the first event: 0, 300, 454, 454 (kick-off), 514.
    # Five minutes back from 514 is 214, so P1 45:00 is out and P1 50:00 is in.
    assert clocks(w, FIVE) == [(1, 3000), (1, 3154), (2, 2700), (2, 2760)]


def test_per_period_mode_restarts_at_kick_off() -> None:
    events = [event(1, 3000), event(1, 3154), event(2, 2700), event(2, 2760)]
    w = windows_after(events, WindowMode.PER_PERIOD)
    assert clocks(w, FIVE) == [(2, 2700), (2, 2760)]


def test_per_period_mode_at_kick_off_drops_the_previous_period() -> None:
    # The 1st half's last event and the 2nd-half kick-off share a play time.
    w = windows_after([event(1, 3154), event(2, 2700)], WindowMode.PER_PERIOD)
    assert clocks(w, FIVE) == [(2, 2700)]


def test_shootout_is_ignored() -> None:
    end_of_extra_time = event(4, 7447)
    w = windows_after([event(4, 7400), end_of_extra_time, event(5, 0), event(5, 60)])
    assert w.now == MatchTime(4, 7447)
    assert clocks(w, FIVE) == [(4, 7400), (4, 7447)]


def test_old_events_are_evicted_from_the_store() -> None:
    store = InMemoryStateStore()
    w = SlidingWindows(store, match_id=7)
    for item in timed([event(1, s) for s in (0, 100, 700, 800)]):
        w.add(item)
    kept = [i.play_s for i in store.query(7, -math.inf, math.inf)]
    assert kept == [700, 800]  # 800 - 600 = 200, so 0 and 100 are gone


def test_asking_for_a_window_longer_than_kept_is_an_error() -> None:
    w = windows_after([event(1, 0)])
    with pytest.raises(ValueError, match="longer than the longest"):
        w.events(TEN + 1)


def test_lengths_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        SlidingWindows(InMemoryStateStore(), match_id=1, lengths_s=(300, 0))


def test_reset_clears_the_windows_and_the_store() -> None:
    store = InMemoryStateStore()
    w = SlidingWindows(store, match_id=1)
    for item in timed([event(1, 10), event(1, 20)]):
        w.add(item)
    w.reset()
    assert w.now is None
    assert w.events(FIVE) == []
    assert store.query(1, -math.inf, math.inf) == []


def test_latest_is_the_newest_event_added() -> None:
    events = [event(1, 0), event(1, 100), event(5, 0)]
    w = windows_after(events)
    assert w.latest is not None and w.latest.event is events[1]  # the shootout is ignored
    assert windows_after([]).latest is None


def test_covered_grows_until_the_window_is_full() -> None:
    assert windows_after([]).covered_s(FIVE) == 0
    assert windows_after([event(1, 30)]).covered_s(FIVE) == 0
    w = windows_after([event(1, 30), event(1, 150)])
    assert w.covered_s(FIVE) == 120
    w = windows_after([event(1, 30), event(1, 500)])
    assert (w.covered_s(FIVE), w.covered_s(TEN)) == (FIVE, 470)


def test_covered_runs_across_half_time_in_continuous_mode() -> None:
    w = windows_after([event(1, 0), event(1, 400), event(2, 2700), event(2, 2760)])
    assert (w.covered_s(FIVE), w.covered_s(TEN)) == (FIVE, 460)


def test_covered_restarts_at_kick_off_in_per_period_mode() -> None:
    events = [event(1, 0), event(1, 400), event(2, 2700), event(2, 2760)]
    w = windows_after(events, WindowMode.PER_PERIOD)
    assert (w.covered_s(FIVE), w.covered_s(TEN)) == (60, 60)


def test_reset_starts_covered_again() -> None:
    w = windows_after([event(1, 0), event(1, 400)])
    w.reset()
    for item in timed([event(1, 1000), event(1, 1010)]):
        w.add(item)
    assert w.covered_s(FIVE) == 10
