from engine.metrics import MetricsConfig, XTGrid
from engine.pipeline import Pipeline
from engine.schema.event_schema import MatchEvent
from engine.schema.feed_schema import FeedMessage
from engine.schema.feed_schema import FeedMessageKind as K
from engine.ticks import Tick, Ticker
from engine.windows import InMemoryStateStore
from tests.factories import AWAY, HOME, event, feed_event, feed_marker

METRICS = MetricsConfig(XTGrid.from_lists([[0.0] * 12] * 8))


def match(*times: tuple[int, float]) -> list[MatchEvent]:
    """Events at the given (period, clock)s with offsets 0, 1, 2..., teams taking turns."""
    return [event(p, c, offset=i, team=(HOME, AWAY)[i % 2]) for i, (p, c) in enumerate(times)]


def ticks(
    *msgs: FeedMessage, ticker: Ticker | None = None, pipeline: Pipeline | None = None
) -> list[Tick]:
    t = ticker or Ticker(METRICS)
    p = pipeline or Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    return [tick for msg in msgs for item in p.handle(msg) if (tick := t.observe(p, item))]


def start(head: int | None = None) -> FeedMessage:
    return feed_marker(K.match_start, 0, head=head)


def at(ts: list[Tick]) -> list[tuple[int, float]]:
    return [(t.item.event.period, t.item.event.match_clock_s) for t in ts]


def test_a_tick_is_the_first_event_past_each_30s_of_play() -> None:
    e = match((1, 0), (1, 10), (1, 29), (1, 30), (1, 45), (1, 61), (1, 200), (1, 205))
    assert at(ticks(start(), *map(feed_event, e))) == [(1, 30), (1, 61), (1, 200)]


def test_ticks_count_play_time_across_half_time() -> None:
    e = match((1, 0), (1, 20), (2, 2700), (2, 2705), (2, 2712))  # 2712 is 32s of play
    assert at(ticks(start(), *map(feed_event, e))) == [(2, 2712)]


def test_the_shootout_has_no_ticks() -> None:
    e = match((1, 0), (1, 10), (5, 0), (5, 40), (5, 80))
    assert ticks(start(), *map(feed_event, e)) == []


def test_ticks_wait_for_both_teams() -> None:
    e = [event(1, c, offset=i) for i, c in enumerate((0, 30, 60))]
    e += [event(1, 70, offset=3, team=AWAY), event(1, 90, offset=4)]
    [tick] = ticks(start(), *map(feed_event, e))
    assert at([tick]) == [(1, 90)]  # not 70: that tick went by at 60
    assert tick.team_ids == (HOME.id, AWAY.id)
    assert tick.teams == {HOME.id: HOME, AWAY.id: AWAY}


def test_the_tick_length_is_configurable() -> None:
    e = match(*((1, float(s)) for s in range(0, 200, 30)))
    assert at(ticks(start(), *map(feed_event, e), ticker=Ticker(METRICS, tick_s=60))) == [
        (1, 60),
        (1, 120),
        (1, 180),
    ]


def test_a_tick_shows_the_match_as_of_its_event() -> None:
    e = match((1, 0), (1, 10), (1, 30), (1, 40))
    t, p = Ticker(METRICS), Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    seen = []
    for msg in (start(), *map(feed_event, e)):
        for item in p.handle(msg):
            if tick := t.observe(p, item):
                assert (tick.play_s, tick.metrics, tick.generation) == (30, METRICS, 1)
                assert tick.replay is False
                seen.append([x.offset for x in tick.events(300)])
                seen.append([x.offset for x in tick.events(25)])
    assert seen == [[0, 1, 2], [1, 2]]  # not 40: it had not happened yet


def test_ticks_while_catching_up_are_replays() -> None:
    e = match(*((1, float(s)) for s in range(0, 200, 30)))
    replays = [t.replay for t in ticks(start(head=4), *map(feed_event, e))]
    assert replays == [True, True, True, False, False, False]  # offsets 1, 2, 3 | 4, 5, 6


def test_ticks_start_over_with_the_match() -> None:
    e = match(*((1, float(s)) for s in range(0, 100, 30)))
    t, p = Ticker(METRICS), Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    first = ticks(start(), *map(feed_event, e), ticker=t, pipeline=p)
    seek = feed_marker(K.reset, 2, clock_s=60)
    again = ticks(seek, *map(feed_event, e), ticker=t, pipeline=p)
    assert at(again) == at(first) == [(1, 30), (1, 60), (1, 90)]
    # The seek lands on offset 2, so the tick at offset 1 is the only replay.
    assert [(x.generation, x.replay) for x in again] == [(2, True), (2, False), (2, False)]
