import math
from collections.abc import Callable

import pytest

from engine.clock import TimedEvent
from engine.windows import InMemoryStateStore, StateStore
from tests.factories import event

# Every StateStore implementation must pass these. Add new ones here.
STORES: list[Callable[[], StateStore]] = [InMemoryStateStore]


@pytest.fixture(params=STORES, ids=lambda make: make.__name__)
def store(request: pytest.FixtureRequest) -> StateStore:
    make: Callable[[], StateStore] = request.param
    return make()


def at(play_s: float, id: str | None = None) -> TimedEvent:
    return TimedEvent(event(1, play_s, id=id), play_s)


def everything(store: StateStore, match_id: int) -> list[float]:
    return [i.play_s for i in store.query(match_id, -math.inf, math.inf)]


def test_query_is_open_at_the_start_and_closed_at_the_end(store: StateStore) -> None:
    for s in (0, 10, 20, 30, 40):
        store.append(1, at(s))
    assert [i.play_s for i in store.query(1, 10, 30)] == [20, 30]


def test_query_of_unknown_match_is_empty(store: StateStore) -> None:
    assert store.query(99, 0, 100) == []


def test_equal_play_times_are_kept_in_append_order(store: StateStore) -> None:
    store.append(1, at(5, id="a"))
    store.append(1, at(5, id="b"))
    assert [i.event.id for i in store.query(1, 0, 5)] == ["a", "b"]


def test_append_rejects_going_back_in_play_time(store: StateStore) -> None:
    store.append(1, at(10))
    with pytest.raises(ValueError, match="before the newest"):
        store.append(1, at(5))


def test_evict_before_keeps_the_boundary(store: StateStore) -> None:
    for s in (0, 10, 20):
        store.append(1, at(s))
    store.evict_before(1, 10)
    assert everything(store, 1) == [10, 20]


def test_matches_are_kept_apart(store: StateStore) -> None:
    store.append(1, at(0))
    store.append(1, at(10))
    store.append(2, at(3))
    store.evict_before(1, 5)
    assert everything(store, 1) == [10]
    assert everything(store, 2) == [3]
    store.reset(1)
    assert everything(store, 1) == []
    assert everything(store, 2) == [3]
