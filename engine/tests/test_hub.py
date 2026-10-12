import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing

import pytest

from engine.hub import MatchHub
from engine.schema.engine_status_schema import EngineState, EngineStatus
from engine.schema.match_reset_schema import MatchReset
from engine.schema.metric_schema import MetricSnapshot, TeamMetrics
from tests.factories import alert


def snap(offset: int) -> MetricSnapshot:
    teams = [
        TeamMetrics(team_id=t, field_tilt=0.5, xt_added=0, xt_velocity=0, pressure_index=0)
        for t in (1, 2)
    ]
    return MetricSnapshot(
        schema_version=1,
        match_id=1,
        offset=offset,
        period=1,
        match_clock_s=offset,
        window_s=300,
        teams=teams,
    )


def status(released: int) -> EngineStatus:
    return EngineStatus(
        schema_version=1,
        state=EngineState.live,
        generation=1,
        match_id=1,
        released=released,
        buffered=0,
        late_dropped=0,
        duplicates=0,
    )


def reset(generation: int, match_id: int | None = 1) -> MatchReset:
    return MatchReset(schema_version=1, generation=generation, match_id=match_id)


async def take[T](sub: AsyncIterator[T], n: int) -> list[T]:
    """The next n updates; fails rather than hangs if they don't come."""
    async with asyncio.timeout(1):
        return [await anext(sub) for _ in range(n)]


async def test_a_subscriber_starts_with_a_reset_then_gets_updates_as_they_happen() -> None:
    hub = MatchHub()
    sub = hub.subscribe()
    assert await take(sub, 1) == [reset(0, None)]
    hub.start(1, 1)
    hub.set_status(status(0))
    hub.add(snap(1), alert(1))
    assert await take(sub, 4) == [reset(1), status(0), snap(1), alert(1)]


async def test_a_late_subscriber_gets_the_latest_status_and_the_history_first() -> None:
    hub = MatchHub()
    hub.start(1, 1)
    hub.set_status(status(0))
    hub.add(snap(1))
    hub.set_status(status(5))
    hub.add(alert(2), snap(3))
    sub = hub.subscribe()
    assert await take(sub, 5) == [reset(1), status(5), snap(1), alert(2), snap(3)]
    hub.add(snap(4))
    assert await take(sub, 1) == [snap(4)]
    assert (hub.snapshots, hub.alerts) == ([snap(1), snap(3), snap(4)], [alert(2)])


async def test_starting_over_clears_the_history_and_status() -> None:
    hub = MatchHub()
    hub.start(1, 1)
    hub.set_status(status(0))
    hub.add(snap(1), alert(1))
    hub.start(2, 1)
    assert (hub.generation, hub.status, hub.snapshots, hub.alerts) == (2, None, [], [])
    sub = hub.subscribe()
    hub.add(snap(9))
    assert await take(sub, 2) == [reset(2), snap(9)]


async def test_an_unchanged_status_is_not_published() -> None:
    hub = MatchHub()
    sub = hub.subscribe()
    await anext(sub)
    hub.set_status(status(1))
    hub.set_status(status(1))
    hub.set_status(status(2))
    hub.add(snap(1))
    assert await take(sub, 3) == [status(1), status(2), snap(1)]


async def test_a_subscriber_that_falls_behind_is_dropped_and_reconnecting_catches_up(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hub = MatchHub(max_pending=2)
    hub.start(1, 1)
    slow, fast = hub.subscribe(), hub.subscribe()
    assert await anext(slow) == await anext(fast) == reset(1)
    hub.add(snap(1))
    assert await take(fast, 1) == [snap(1)]
    with caplog.at_level(logging.WARNING):
        hub.add(snap(2), snap(3))  # slow now has 3 waiting, fast 2
    assert "dropping a subscriber 2 updates behind" in caplog.text
    assert hub.subscribers == 1
    with pytest.raises(StopAsyncIteration):
        async with asyncio.timeout(1):
            await anext(slow)
    assert await take(fast, 2) == [snap(2), snap(3)]
    again = hub.subscribe()
    assert await take(again, 4) == [reset(1), snap(1), snap(2), snap(3)]


async def test_closing_a_subscription_unsubscribes() -> None:
    hub = MatchHub()
    async with aclosing(hub.subscribe()) as sub:
        await anext(sub)
        assert hub.subscribers == 1
    assert hub.subscribers == 0
    hub.add(snap(1))


async def test_closing_the_hub_ends_every_subscription_now_and_later() -> None:
    hub = MatchHub()
    hub.start(1, 1)
    waiting, behind = hub.subscribe(), hub.subscribe()
    assert await anext(waiting) == await anext(behind) == reset(1)
    pending = asyncio.ensure_future(anext(waiting))
    await asyncio.sleep(0)  # let it wait for the next update
    hub.add(snap(1))
    assert await pending == snap(1)
    hub.add(snap(2))
    hub.close()
    assert hub.subscribers == 0
    for sub in (waiting, behind):
        with pytest.raises(StopAsyncIteration):
            async with asyncio.timeout(1):
                await anext(sub)
    with pytest.raises(StopAsyncIteration):
        await anext(hub.subscribe())
