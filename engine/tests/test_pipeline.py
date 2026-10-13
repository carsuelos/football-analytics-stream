import pytest

from engine.pipeline import Pipeline
from engine.schema.event_schema import MatchEvent
from engine.schema.feed_schema import FeedMessage
from engine.schema.feed_schema import FeedMessageKind as K
from engine.windows import InMemoryStateStore, WindowMode
from tests.factories import AWAY, event, feed_event, feed_marker


def start(offset: int = 0, match_id: int = 1) -> FeedMessage:
    return feed_marker(K.match_start, offset, match_id=match_id)


def match(clocks: list[tuple[int, float]], match_id: int = 1) -> list[MatchEvent]:
    """Events at the given (period, clock)s with offsets 0, 1, 2..."""
    return [event(p, c, offset=i, match_id=match_id) for i, (p, c) in enumerate(clocks)]


def feed(p: Pipeline, *msgs: FeedMessage) -> list[tuple[int, float]]:
    """Handle msgs; return the (period, clock) of every event released."""
    out = []
    for msg in msgs:
        out += [(i.event.period, i.event.match_clock_s) for i in p.handle(msg)]
    return out


def window(p: Pipeline, length_s: float = 300) -> list[str]:
    assert p.windows is not None
    return [i.event.id for i in p.windows.events(length_s)]


def test_events_come_out_in_order_once_the_watermark_passes() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=5)
    e = match([(1, 0), (1, 3), (1, 1), (1, 10)])  # (1, 1) arrives late but within 5s
    assert feed(p, start(), *map(feed_event, e)) == [(1, 0), (1, 1), (1, 3)]
    assert len(p.buffer) == 1
    assert feed(p, feed_marker(K.match_end, 4)) == [(1, 10)]
    assert p.ended
    assert window(p) == [e[0].id, e[2].id, e[1].id, e[3].id]
    assert p.clock.play_s == 10


def test_starting_over_rebuilds_the_same_state_from_the_replay() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    e = match([(1, 0), (1, 60), (1, 400), (1, 500)])
    feed(p, start(), *map(feed_event, e))
    before = window(p)
    assert before == [e[2].id, e[3].id]

    # The DVR seeks back to 01:00: it starts over, then replays offsets 0-1.
    feed(p, feed_marker(K.match_start, 0, head=2))
    assert p.windows is not None
    assert p.windows.now is None
    assert p.rebuilding
    released = [p.handle(feed_event(x)) for x in e[:2]]
    assert not p.rebuilding
    assert all(p.is_replay(i) for batch in released for i in batch)
    assert window(p) == [e[0].id, e[1].id]
    assert p.buffer.stats.duplicates == 0  # replayed ids are not duplicates

    # Play on from the seek point: new events are not replays.
    later = p.handle(feed_event(e[2]))
    assert [p.is_replay(i) for i in later] == [False]


def test_match_start_switches_to_a_new_match_and_forgets_the_old_one() -> None:
    store = InMemoryStateStore()
    p = Pipeline(store, allowed_lateness_s=0)
    feed(p, start(), *map(feed_event, match([(1, 0), (1, 10)])))
    assert store.query(1, -1, 1e9)

    second = match([(1, 0)], match_id=2)
    assert feed(p, start(match_id=2), feed_event(second[0])) == [(1, 0)]
    assert p.match_id == 2
    assert store.query(1, -1, 1e9) == []


def test_reloading_the_same_match_starts_over() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    e = match([(1, 0), (1, 10)])
    feed(p, start(), *map(feed_event, e), feed_marker(K.match_end, 2))
    assert feed(p, start(), feed_event(e[0])) == [(1, 0)]
    assert not p.ended
    assert window(p) == [e[0].id]


def test_window_mode_is_passed_to_the_windows() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0, window_mode=WindowMode.PER_PERIOD)
    e = match([(1, 2800), (2, 2700)])
    feed(p, start(), *map(feed_event, e))
    assert window(p) == [e[1].id]


def test_late_events_are_dropped_and_counted() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=2)
    e = match([(1, 0), (1, 10), (1, 5)])
    assert feed(p, start(), *map(feed_event, e)) == [(1, 0)]
    assert p.buffer.stats.late_dropped == 1


def test_event_before_match_start_is_an_error() -> None:
    p = Pipeline(InMemoryStateStore())
    with pytest.raises(ValueError, match="before match_start"):
        p.handle(feed_event(event(1, 0)))


def test_event_for_another_match_is_an_error() -> None:
    p = Pipeline(InMemoryStateStore())
    p.handle(start(match_id=1))
    with pytest.raises(ValueError, match="for match 2"):
        p.handle(feed_event(event(1, 0, match_id=2, team=AWAY)))


def test_team_ids_once_both_teams_have_appeared_in_order() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    feed(p, start(), feed_event(event(1, 0, offset=0, team=AWAY)))
    assert p.team_ids is None
    feed(p, feed_event(event(1, 1, offset=1)), feed_event(event(1, 2, offset=2, team=AWAY)))
    assert p.team_ids == (AWAY.id, 1)
    assert p.teams[AWAY.id] == AWAY


def test_teams_are_forgotten_on_starting_over() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    feed(
        p, start(), feed_event(event(1, 0, offset=0)), feed_event(event(1, 1, offset=1, team=AWAY))
    )
    assert p.team_ids is not None
    feed(p, feed_marker(K.match_start, 0, head=2))
    assert p.team_ids is None and p.teams == {}


def test_events_already_published_at_match_start_are_a_catch_up() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    e = match([(1, 0), (1, 10), (1, 20)])
    feed(p, feed_marker(K.match_start, 0, head=2))
    assert p.rebuilding
    released = [i for x in e for i in p.handle(feed_event(x))]
    assert not p.rebuilding
    assert [p.is_replay(i) for i in released] == [True, True, False]


def test_a_reconnect_keeps_the_state_and_marks_missed_events_as_catch_up() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    e = match([(1, 0), (1, 10), (1, 20), (1, 30)])
    feed(p, start(), *map(feed_event, e[:2]))
    # Dropped after offset 1; the simulator published offset 2 while we were away.
    feed(p, feed_marker(K.match_start, 2, head=3))
    released = [i for x in e[2:] for i in p.handle(feed_event(x))]
    assert window(p) == [x.id for x in e]
    assert [p.is_replay(i) for i in released] == [True, False]


def test_a_reconnect_during_a_replay_keeps_replaying_to_the_head() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    e = match([(1, 0), (1, 10), (1, 20)])
    restart = feed_marker(K.match_start, 0, head=3)
    feed(p, start(), *map(feed_event, e), restart, feed_event(e[0]))
    feed(p, feed_marker(K.match_start, 1, head=3))
    assert window(p) == [e[0].id]
    released = [i for x in e[1:] for i in p.handle(feed_event(x))]
    assert [p.is_replay(i) for i in released] == [True, True]


def test_the_head_on_a_resume_wins_over_an_older_one() -> None:
    # The viewer seeked back to offset 3, then forward to offset 2 during the
    # replay: offset 2 on is played, not replayed.
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    e = match([(1, 0), (1, 10), (1, 20)])
    restart = feed_marker(K.match_start, 0, head=3)
    feed(p, start(), *map(feed_event, e), restart, feed_event(e[0]))
    feed(p, feed_marker(K.match_start, 1, head=2))
    released = [i for x in e[1:] for i in p.handle(feed_event(x))]
    assert [p.is_replay(i) for i in released] == [True, False]


@pytest.mark.parametrize("offset", [1, 3])  # behind us, or ahead with a gap
def test_a_match_start_not_at_our_next_offset_starts_over(offset: int) -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    e = match([(1, 0), (1, 10)])
    feed(p, start(), *map(feed_event, e))
    feed(p, feed_marker(K.match_start, offset, head=3))
    assert p.windows is not None and p.windows.now is None


def test_the_generation_goes_up_each_time_the_pipeline_starts_over() -> None:
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    assert p.generation == 0
    feed(p, start(), *map(feed_event, match([(1, 0), (1, 10)])))
    assert p.generation == 1
    feed(p, feed_marker(K.match_start, 2, head=2))  # a reconnect
    assert p.generation == 1
    feed(p, feed_marker(K.match_start, 0, head=1))  # the DVR seeks back
    assert p.generation == 2
