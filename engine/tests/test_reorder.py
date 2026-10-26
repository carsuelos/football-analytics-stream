import random

import pytest

from engine.clock import MatchTime, ReorderBuffer
from engine.schema.event_schema import MatchEvent
from tests.factories import event, times


def push_all(buf: ReorderBuffer, events: list[MatchEvent]) -> list[MatchEvent]:
    out: list[MatchEvent] = []
    for e in events:
        out += buf.push(e)
    return out


def test_zero_lateness_releases_in_order_events_at_once() -> None:
    buf = ReorderBuffer(allowed_lateness_s=0)
    assert times(buf.push(event(1, 0))) == [(1, 0)]
    assert times(buf.push(event(1, 5))) == [(1, 5)]
    assert len(buf) == 0


def test_holds_events_until_the_watermark_passes() -> None:
    buf = ReorderBuffer(allowed_lateness_s=5)
    assert buf.push(event(1, 0)) == []
    assert buf.push(event(1, 3)) == []
    assert buf.watermark == MatchTime(1, -2)
    # 7 - 5 = 2: releases 0 but not 3.
    assert times(buf.push(event(1, 7))) == [(1, 0)]
    assert len(buf) == 2


def test_late_events_within_lateness_come_out_in_order() -> None:
    buf = ReorderBuffer(allowed_lateness_s=5)
    out = push_all(buf, [event(1, 10), event(1, 12), event(1, 8), event(1, 11), event(1, 20)])
    out += buf.flush()
    assert times(out) == [(1, 8), (1, 10), (1, 11), (1, 12), (1, 20)]
    assert buf.stats.late_dropped == 0


def test_events_behind_the_watermark_are_dropped_and_counted() -> None:
    buf = ReorderBuffer(allowed_lateness_s=5)
    push_all(buf, [event(1, 0), event(1, 20)])  # watermark is now 15
    assert buf.push(event(1, 14)) == []
    assert buf.stats.late_dropped == 1
    assert times(buf.flush()) == [(1, 20)]


def test_watermark_never_moves_backwards() -> None:
    buf = ReorderBuffer(allowed_lateness_s=5)
    push_all(buf, [event(1, 20), event(1, 17)])  # 17 is late but within lateness
    assert buf.watermark == MatchTime(1, 15)
    assert buf.push(event(1, 13)) == []
    assert buf.stats.late_dropped == 1


def test_duplicates_are_dropped_even_after_release() -> None:
    buf = ReorderBuffer(allowed_lateness_s=0)
    assert len(buf.push(event(1, 0, id="a"))) == 1
    assert buf.push(event(1, 0, id="a")) == []
    assert buf.stats.duplicates == 1
    assert buf.stats.late_dropped == 0


def test_a_new_period_releases_the_previous_one() -> None:
    # The second half starts at 45:00, before the end of first-half stoppage time.
    buf = ReorderBuffer(allowed_lateness_s=5)
    push_all(buf, [event(1, 3150), event(1, 3154)])
    assert times(buf.push(event(2, 2700))) == [(1, 3150), (1, 3154)]
    # Too late now: the first half is closed.
    assert buf.push(event(1, 3155)) == []
    assert buf.stats.late_dropped == 1


def test_reset_forgets_ids_so_a_replay_is_accepted() -> None:
    buf = ReorderBuffer(allowed_lateness_s=0)
    push_all(buf, [event(1, 0, id="a"), event(1, 60, id="b")])
    buf.reset()
    assert buf.watermark is None
    assert times(push_all(buf, [event(1, 0, id="a"), event(1, 60, id="b")])) == [(1, 0), (1, 60)]
    assert buf.stats.duplicates == 0


def test_negative_lateness_is_rejected() -> None:
    with pytest.raises(ValueError):
        ReorderBuffer(allowed_lateness_s=-1)


@pytest.mark.parametrize("seed", range(5))
def test_restores_order_under_simulator_style_jitter(seed: int) -> None:
    """Delay each event by up to max_delay and deliver them in arrival order,
    the way the simulator's -jitter flag does. With a lateness of at least
    max_delay, every event comes out, in order."""
    rng = random.Random(seed)
    max_delay = 3.0
    original = [
        event(p, base + i * rng.uniform(0, 2))
        for p, base in [(1, 0), (2, 2700)]
        for i in range(300)
    ]
    original.sort(key=MatchTime.of)
    arrivals = sorted(
        original, key=lambda e: (e.period, e.match_clock_s + rng.uniform(0, max_delay))
    )
    assert times(arrivals) != times(original), "the test should actually shuffle"

    buf = ReorderBuffer(allowed_lateness_s=max_delay)
    out = push_all(buf, arrivals) + buf.flush()

    assert [e.id for e in out] == [e.id for e in original]
    assert buf.stats.late_dropped == 0


def test_release_all_lets_out_what_is_held_and_keeps_the_order() -> None:
    buf = ReorderBuffer(allowed_lateness_s=5)
    assert times(push_all(buf, [event(1, 352), event(1, 356)])) == []  # held for the watermark
    assert times(buf.release_all()) == [(1, 352), (1, 356)]  # the feed went quiet
    assert buf.push(event(1, 353)) == []  # earlier than released: late
    assert buf.stats.late_dropped == 1
    assert times(push_all(buf, [event(1, 470), event(1, 480)])) == [
        (1, 470)
    ]  # back to the watermark
    assert buf.release_all() and buf.release_all() == []
