"""Read the broadcast from a Kafka topic.

The simulator publishes every match it broadcasts to the topic (see its kafka
package): a match_start, the events in feed order, then a match_end, keyed by
match_id. The topic keeps them all, so to follow the current match the source:

  1. finds the latest match_start on the topic, reading each partition
     backwards a chunk at a time, and picks the newest across partitions;
  2. reads that match from its start up to where the partition ended when it
     looked (the catch-up), then passes on a match_start whose head marks
     those events as already happened, and the events themselves;
  3. follows on live, switching to each new match as its match_start arrives
     on any partition. Other matches' events are ignored.

librdkafka reconnects by itself and keeps its position, so the stream never
breaks the way a WebSocket can; there is nothing to resume.

The client is confluent-kafka (librdkafka). It uses only the plain Kafka
protocol, so it works against Redpanda locally and Azure Event Hubs in the
cloud, configured from KAFKA_* environment variables (see config_from_env).
Its calls block, so they run on a thread of their own.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import ValidationError

from engine.schema.feed_schema import FeedMarker, FeedMessage, FeedMessageKind

log = logging.getLogger(__name__)

ENV_PREFIX = "KAFKA_"
SCAN_CHUNK = 1000
"""Messages read at a time when looking backwards for the latest match_start."""
POLL_TIMEOUT_S = 1.0
RETRY_S = 2.0


def config_from_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The client configuration in environ: each KAFKA_* variable sets the
    librdkafka property named by the rest of it, lowercased, with dots for
    underscores. KAFKA_BOOTSTRAP_SERVERS=redpanda:9092 sets bootstrap.servers;
    Azure Event Hubs also needs KAFKA_SECURITY_PROTOCOL=SASL_SSL,
    KAFKA_SASL_MECHANISM=PLAIN, KAFKA_SASL_USERNAME='$ConnectionString' and
    KAFKA_SASL_PASSWORD. The simulator reads the same variables."""
    return {
        name.removeprefix(ENV_PREFIX).lower().replace("_", "."): value
        for name, value in environ.items()
        if name.startswith(ENV_PREFIX) and name != ENV_PREFIX
    }


@dataclass(frozen=True, slots=True)
class Record:
    partition: int
    offset: int
    timestamp_ms: int
    value: bytes


@dataclass(frozen=True, slots=True)
class Eof:
    """The reader has reached the end of a partition."""

    partition: int


class Broker(Protocol):
    """The blocking calls KafkaSource makes on one topic."""

    def partitions(self) -> list[int]:
        """The topic's partitions; empty if it doesn't exist (yet)."""
        ...

    def watermarks(self, partition: int) -> tuple[int, int]:
        """The partition's first offset and the offset after its last message."""
        ...

    def read(self, partition: int, start: int, end: int) -> list[Record]:
        """The partition's messages from offset start up to end."""
        ...

    def assign(self, positions: Mapping[int, int]) -> None:
        """Read each partition from its offset in positions."""
        ...

    def poll(self, timeout_s: float) -> list[Record | Eof]:
        """What has arrived on the assigned partitions, waiting up to timeout_s."""
        ...

    def close(self) -> None: ...


class KafkaSource:
    """An EventSource reading the broadcast from a Kafka topic.

    It never gives up; cancel the consuming task to stop it.
    """

    def __init__(
        self,
        config: Mapping[str, str],
        topic: str,
        *,
        connect: Callable[[Mapping[str, str], str], Broker] | None = None,
        scan_chunk: int = SCAN_CHUNK,
        retry_s: float = RETRY_S,
    ) -> None:
        self.config = dict(config)
        self.topic = topic
        self._connect = connect or _confluent
        self._scan_chunk = scan_chunk
        self._retry_s = retry_s

    async def subscribe(self, from_offset: int = 0) -> AsyncGenerator[FeedMessage]:
        loop = asyncio.get_running_loop()
        # One thread: the client isn't shared between threads, and close waits
        # for a poll in progress.
        thread = ThreadPoolExecutor(1, thread_name_prefix="kafka")

        async def call[T](fn: Callable[[], T]) -> T:
            return await loop.run_in_executor(thread, fn)

        try:
            broker = await call(lambda: self._connect(self.config, self.topic))
            try:
                while not (partitions := await call(broker.partitions)):
                    log.warning("topic %s not found; retrying in %gs", self.topic, self._retry_s)
                    await asyncio.sleep(self._retry_s)
                positions, catch_up = await call(lambda: self._locate(broker, partitions))
                await call(lambda: broker.assign(positions))
                follower = _Follower(from_offset, catch_up)
                log.info("reading %s from %s", self.topic, positions)
                while True:
                    for item in await call(lambda: broker.poll(POLL_TIMEOUT_S)):
                        for msg in follower.receive(item):
                            yield msg
            finally:
                await call(broker.close)
        finally:
            thread.shutdown(wait=False)

    def _locate(
        self, broker: Broker, partitions: list[int]
    ) -> tuple[dict[int, int], "_CatchUp | None"]:
        """Where to read each partition from: the latest match_start on the
        topic, and the end of every other partition."""
        positions: dict[int, int] = {}
        latest: Record | None = None
        ends: dict[int, int] = {}
        for p in partitions:
            low, high = broker.watermarks(p)
            positions[p] = ends[p] = high
            start = self._latest_start(broker, p, low, high)
            if start and (latest is None or start.timestamp_ms > latest.timestamp_ms):
                latest = start
        if latest is None:
            log.info("no match on %s yet", self.topic)
            return positions, None
        positions[latest.partition] = latest.offset
        return positions, _CatchUp(latest.partition, ends[latest.partition])

    def _latest_start(self, broker: Broker, partition: int, low: int, high: int) -> Record | None:
        end = high
        while end > low:
            start = max(low, end - self._scan_chunk)
            for record in reversed(broker.read(partition, start, end)):
                msg = _parse(record)
                if msg and msg.kind is FeedMessageKind.match_start:
                    return record
            end = start
        return None


@dataclass(slots=True)
class _CatchUp:
    """Reading a match that had started before we looked, up to end."""

    partition: int
    end: int
    messages: list[FeedMessage] = field(default_factory=list)


class _Follower:
    """Turns the topic's records into the stream of one match at a time."""

    def __init__(self, from_offset: int, catch_up: _CatchUp | None) -> None:
        self._from_offset = from_offset
        self._catch_up = catch_up
        self._match: tuple[int, int] | None = None
        """(partition, match_id) of the match being followed."""

    def receive(self, item: Record | Eof) -> list[FeedMessage]:
        cu = self._catch_up
        if isinstance(item, Eof):
            return self._finish_catch_up() if cu and item.partition == cu.partition else []
        msg = _parse(item)
        if cu and item.partition == cu.partition and item.offset < cu.end:
            # A partition may carry other matches too; keep this one's.
            if msg and (not cu.messages or _match_id(msg) == _match_id(cu.messages[0])):
                cu.messages.append(msg)
            return self._finish_catch_up() if item.offset >= cu.end - 1 else []
        out = self._finish_catch_up() if cu else []
        if msg:
            out += self._live(item.partition, msg)
        return out

    def _live(self, partition: int, msg: FeedMessage) -> list[FeedMessage]:
        if msg.kind is FeedMessageKind.match_start:
            start = _marker(msg)
            self._match = (partition, start.match_id)
            log.info("match %d started on partition %d", start.match_id, partition)
            return [_start(start.model_copy(update={"head": None}))]
        if self._match == (partition, _match_id(msg)):
            return [msg]
        return []

    def _finish_catch_up(self) -> list[FeedMessage]:
        """The match so far, after a match_start whose head covers all of it."""
        cu, self._catch_up = self._catch_up, None
        if cu is None or not cu.messages or cu.messages[0].kind is not FeedMessageKind.match_start:
            return []
        first, rest = _marker(cu.messages[0]), cu.messages[1:]
        events = [m.event for m in rest if m.event]
        head = max((e.offset + 1 for e in events), default=0)
        offset = self._from_offset if self._from_offset <= head else 0
        before = [e for e in events if e.offset == offset - 1]
        period, clock = (
            (before[-1].period, before[-1].match_clock_s)
            if before
            else (first.period, first.match_clock_s)
        )
        self._match = (cu.partition, first.match_id)
        log.info("match %d: caught up to offset %d", first.match_id, head)
        start = FeedMarker(
            match_id=first.match_id, offset=offset, period=period, match_clock_s=clock, head=head
        )
        return [_start(start), *(m for m in rest if m.event is None or m.event.offset >= offset)]


def _parse(record: Record) -> FeedMessage | None:
    """The record's message, or None (logged) if it isn't a valid one."""
    try:
        msg = FeedMessage.model_validate_json(record.value)
    except ValidationError as e:
        problem = str(e)
    else:
        if (msg.event if msg.kind is FeedMessageKind.event else msg.marker) is not None:
            return msg
        problem = f"{msg.kind} message without its payload"
    log.warning(
        "skipping a bad message at partition %d offset %d: %s",
        record.partition,
        record.offset,
        problem,
    )
    return None


def _start(marker: FeedMarker) -> FeedMessage:
    return FeedMessage(schema_version=1, kind=FeedMessageKind.match_start, marker=marker)


def _marker(msg: FeedMessage) -> FeedMarker:
    if msg.marker is None:
        raise ValueError(f"{msg.kind} message without a marker")
    return msg.marker


def _match_id(msg: FeedMessage) -> int | None:
    if msg.event:
        return msg.event.match_id
    return msg.marker.match_id if msg.marker else None


def _confluent(config: Mapping[str, str], topic: str) -> Broker:
    from engine.sources.confluent import ConfluentBroker

    return ConfluentBroker(config, topic)
