"""Read the simulator's WebSocket feed, reconnecting and resuming as needed."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator
from dataclasses import dataclass

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidURI, WebSocketException

from engine.schema.feed_schema import FeedMarker, FeedMessage, FeedMessageKind

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Backoff:
    """Reconnect delays: initial_s, doubling each failed attempt up to max_s."""

    initial_s: float = 0.5
    max_s: float = 10.0

    def delays(self) -> Iterator[float]:
        delay = self.initial_s
        while True:
            yield delay
            delay = min(delay * 2, self.max_s)


DEFAULT_BACKOFF = Backoff()


class WebSocketSource:
    """An EventSource reading the simulator's /feed endpoint.

    Reconnects are hidden from the consumer. After a drop it reconnects with
    ?from_offset=<next offset> and carries on as if the connection had never
    broken:
      - the match_start the server sends on every new connection is dropped
        when it is the same match we were reading;
      - if a different match was loaded while we were away, it starts again
        from offset 0 so the consumer sees the new match from its start.

    It never gives up; cancel the consuming task to stop it.
    """

    def __init__(
        self,
        url: str,
        *,
        backoff: Backoff = DEFAULT_BACKOFF,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.url = url
        self.backoff = backoff
        self._sleep = sleep

    async def subscribe(self, from_offset: int = 0) -> AsyncGenerator[FeedMessage]:
        next_offset = from_offset
        match_id: int | None = None
        reconnecting = False
        delays = self.backoff.delays()
        while True:
            restart_from_zero = False
            try:
                async with connect(f"{self.url}?from_offset={next_offset}") as ws:
                    log.info("connected to %s from offset %d", self.url, next_offset)
                    delays = self.backoff.delays()
                    async for raw in ws:
                        msg = FeedMessage.model_validate_json(raw)
                        if msg.kind is FeedMessageKind.match_start and reconnecting:
                            reconnecting = False
                            start = _marker(msg)
                            if start.match_id == match_id:
                                log.info("resumed match %d at offset %d", match_id, start.offset)
                                continue
                            if start.offset != 0:
                                log.info("match %d was loaded while away", start.match_id)
                                restart_from_zero = True
                                break
                        match_id, next_offset = _advance(msg, match_id, next_offset)
                        yield msg
            except InvalidURI:
                raise
            except (OSError, WebSocketException) as e:
                log.warning("feed connection failed: %r", e)
            else:
                if not restart_from_zero:
                    log.warning("feed closed by the server")
            reconnecting = True
            if restart_from_zero:
                next_offset = 0
                continue
            delay = next(delays)
            log.info("reconnecting in %.1fs", delay)
            await self._sleep(delay)


def _advance(msg: FeedMessage, match_id: int | None, next_offset: int) -> tuple[int | None, int]:
    """The match and the offset to resume from after msg."""
    match msg.kind:
        case FeedMessageKind.event:
            if msg.event is None:
                raise ValueError("event message without an event")
            return msg.event.match_id, msg.event.offset + 1
        case FeedMessageKind.match_start | FeedMessageKind.match_end:
            marker = _marker(msg)
            return marker.match_id, marker.offset
        case FeedMessageKind.reset:
            # A replay from offset 0 follows.
            return _marker(msg).match_id, 0


def _marker(msg: FeedMessage) -> FeedMarker:
    if msg.marker is None:
        raise ValueError(f"{msg.kind} message without a marker")
    return msg.marker
