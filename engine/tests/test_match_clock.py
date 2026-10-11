import pytest

from engine.clock import MatchClock, MatchTime
from tests.factories import event


def test_play_time_runs_across_half_time_without_a_gap() -> None:
    clock = MatchClock()
    play = [
        clock.advance(e).play_s
        for e in [event(1, 0), event(1, 3154), event(2, 2700), event(2, 2760)]
    ]
    assert play == [0, 3154, 3154, 3214]
    assert clock.now == MatchTime(2, 2760)
    assert clock.period_start_play_s == 3154


def test_extra_time_continues_the_axis() -> None:
    clock = MatchClock()
    for e in [event(1, 0), event(1, 2800), event(2, 2700), event(2, 5900), event(3, 5400)]:
        clock.advance(e)
    # 2800 s of first half + 3200 s of second half.
    assert clock.play_s == 6000
    assert clock.period_start_play_s == 6000


def test_rejects_events_out_of_order() -> None:
    clock = MatchClock()
    clock.advance(event(1, 10))
    with pytest.raises(ValueError, match="ReorderBuffer"):
        clock.advance(event(1, 9))


def test_reset_starts_over() -> None:
    clock = MatchClock()
    clock.advance(event(1, 100))
    clock.reset()
    assert clock.now is None
    assert clock.advance(event(1, 0)).play_s == 0
