import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, aclosing, asynccontextmanager
from dataclasses import dataclass
from itertools import islice
from typing import Literal
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import ValidationError
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import InvalidURI

from engine.schema.feed_schema import FeedMessage
from engine.schema.feed_schema import FeedMessageKind as K
from engine.sources import Backoff, WebSocketSource
from tests.factories import event, feed_event, feed_marker


@dataclass
class Connection:
    """What the fake server does for one client connection."""

    send: list[FeedMessage | str]
    then: Literal["close", "drop", "hang"] = "hang"


class FakeFeed:
    """A scripted stand-in for the simulator's /feed.

    Connection n plays script[n]; any later connection hangs with no messages.
    """

    def __init__(self, *script: Connection) -> None:
        self.script = list(script)
        self.from_offsets: list[int] = []

    async def handler(self, ws: ServerConnection) -> None:
        assert ws.request is not None
        query = parse_qs(urlsplit(ws.request.path).query)
        self.from_offsets.append(int(query["from_offset"][0]))
        n = len(self.from_offsets) - 1
        conn = self.script[n] if n < len(self.script) else Connection([])
        for msg in conn.send:
            await ws.send(msg if isinstance(msg, str) else msg.model_dump_json(exclude_none=True))
        match conn.then:
            case "close":
                await ws.close(1001)  # what the simulator sends when it shuts down
            case "drop":
                ws.transport.abort()  # no close frame, like a network failure
            case "hang":
                await ws.wait_closed()


def port_of(server: Server) -> int:
    port: int = next(iter(server.sockets)).getsockname()[1]
    return port


@asynccontextmanager
async def running(feed: FakeFeed) -> AsyncIterator[str]:
    async with serve(feed.handler, "127.0.0.1", 0) as server:
        yield f"ws://127.0.0.1:{port_of(server)}/feed"


class Sleeps:
    """A stand-in for asyncio.sleep that records delays and returns at once."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        await asyncio.sleep(0)


async def take(source: WebSocketSource, n: int, from_offset: int = 0) -> list[FeedMessage]:
    got: list[FeedMessage] = []
    async with asyncio.timeout(5), aclosing(source.subscribe(from_offset)) as stream:
        async for msg in stream:
            got.append(msg)
            if len(got) == n:
                break
    return got


def summary(msgs: list[FeedMessage]) -> list[tuple[str, int, int]]:
    """(kind, match_id, offset) of each message, for readable assertions."""
    out = []
    for m in msgs:
        pos = m.event or m.marker
        assert pos is not None
        out.append((m.kind.value, pos.match_id, pos.offset))
    return out


E = [event(1, s, offset=i) for i, s in enumerate((0, 5, 10, 15))]


def start(offset: int, match_id: int = 1) -> FeedMessage:
    return feed_marker(K.match_start, offset, match_id=match_id)


def test_backoff_doubles_up_to_the_max() -> None:
    assert list(islice(Backoff(1, 5).delays(), 5)) == [1, 2, 4, 5, 5]


async def test_reads_the_feed() -> None:
    feed = FakeFeed(
        Connection([start(0), feed_event(E[0]), feed_event(E[1]), feed_marker(K.match_end, 2)])
    )
    async with running(feed) as url:
        msgs = await take(WebSocketSource(url), 4)
    assert summary(msgs) == [
        ("match_start", 1, 0),
        ("event", 1, 0),
        ("event", 1, 1),
        ("match_end", 1, 2),
    ]
    assert msgs[1].event == E[0]
    assert feed.from_offsets == [0]


async def test_subscribes_from_the_given_offset() -> None:
    feed = FakeFeed(Connection([start(2), feed_event(E[2])]))
    async with running(feed) as url:
        msgs = await take(WebSocketSource(url), 2, from_offset=2)
    assert summary(msgs) == [("match_start", 1, 2), ("event", 1, 2)]
    assert feed.from_offsets == [2]


@pytest.mark.parametrize("how", ["close", "drop"])
async def test_resumes_where_it_left_off(how: Literal["close", "drop"]) -> None:
    feed = FakeFeed(
        Connection([start(0), feed_event(E[0]), feed_event(E[1])], then=how),
        Connection([start(2), feed_event(E[2])]),
    )
    sleeps = Sleeps()
    async with running(feed) as url:
        msgs = await take(WebSocketSource(url, sleep=sleeps), 5)
    # The second match_start is passed on, at the offset where the stream resumes.
    assert summary(msgs) == [
        ("match_start", 1, 0),
        ("event", 1, 0),
        ("event", 1, 1),
        ("match_start", 1, 2),
        ("event", 1, 2),
    ]
    assert feed.from_offsets == [0, 2]
    assert sleeps.delays == [0.5]


async def test_passes_on_the_match_from_kick_off_when_it_was_reloaded_while_away() -> None:
    feed = FakeFeed(
        Connection([start(0), *map(feed_event, E[:3])], then="drop"),
        # We are past the new broadcast's head, so it starts us from offset 0.
        Connection([start(0), feed_event(E[0])], then="drop"),
        Connection([start(1), feed_event(E[1])]),
    )
    async with running(feed) as url:
        msgs = await take(WebSocketSource(url, sleep=Sleeps()), 8)
    assert summary(msgs)[-4:] == [
        ("match_start", 1, 0),
        ("event", 1, 0),
        ("match_start", 1, 1),
        ("event", 1, 1),
    ]
    assert feed.from_offsets == [0, 3, 1]


async def test_starts_over_when_another_match_was_loaded_while_away() -> None:
    other = event(1, 0, offset=0, match_id=2)
    feed = FakeFeed(
        Connection([start(0), feed_event(E[0]), feed_event(E[1])], then="close"),
        Connection([start(2, match_id=2)]),  # the server resumes at our offset, in the new match
        Connection([start(0, match_id=2), feed_event(other)]),
    )
    sleeps = Sleeps()
    async with running(feed) as url:
        msgs = await take(WebSocketSource(url, sleep=sleeps), 5)
    assert summary(msgs) == [
        ("match_start", 1, 0),
        ("event", 1, 0),
        ("event", 1, 1),
        ("match_start", 2, 0),
        ("event", 2, 0),
    ]
    assert feed.from_offsets == [0, 2, 0]
    assert sleeps.delays == [0.5]  # starting over is immediate


async def test_backs_off_until_the_simulator_is_up_then_resets_the_backoff() -> None:
    feed = FakeFeed(
        Connection([start(0)], then="close"),
        Connection([start(0), feed_event(E[0])]),
    )
    async with serve(feed.handler, "127.0.0.1", 0) as server:
        port = port_of(server)
    # Nothing listens on the port now, so connecting fails until the 4th sleep starts the server.
    async with AsyncExitStack() as stack:
        delays: list[float] = []

        async def sleep(delay: float) -> None:
            delays.append(delay)
            if len(delays) == 4:
                await stack.enter_async_context(serve(feed.handler, "127.0.0.1", port))

        source = WebSocketSource(
            f"ws://127.0.0.1:{port}/feed", backoff=Backoff(0.5, 2), sleep=sleep
        )
        msgs = await take(source, 3)
    assert summary(msgs) == [("match_start", 1, 0), ("match_start", 1, 0), ("event", 1, 0)]
    assert delays == [0.5, 1, 2, 2, 0.5]  # back to 0.5 after a successful connection


async def test_an_invalid_message_is_an_error() -> None:
    feed = FakeFeed(Connection(['{"schema_version": 1, "kind": "goal"}']))
    async with running(feed) as url:
        with pytest.raises(ValidationError):
            await take(WebSocketSource(url), 1)


async def test_a_bad_url_is_not_retried() -> None:
    with pytest.raises(InvalidURI):
        await take(WebSocketSource("http://localhost:8080/feed", sleep=Sleeps()), 1)
