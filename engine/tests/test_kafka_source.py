import asyncio
import threading
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import aclosing

import pytest

from engine.schema.feed_schema import FeedMessage
from engine.schema.feed_schema import FeedMessageKind as K
from engine.sources import KafkaSource
from engine.sources.kafka import Broker, Eof, Record, config_from_env
from tests.factories import event, feed_event, feed_marker

TOPIC = "events"


class FakeBroker:
    """A topic in memory. Tests append to it while the source reads it."""

    def __init__(self, *partitions: list[FeedMessage | bytes], exists: bool = True) -> None:
        self._lock = threading.Lock()
        self.logs: list[list[Record]] = []
        self.exists = exists
        self.closed = False
        self.reads: list[tuple[int, int, int]] = []
        self._positions: dict[int, int] = {}
        self.assigned = threading.Event()
        self._eof_sent: set[int] = set()
        self._clock = 0
        for msgs in partitions:
            self.logs.append([])
            for msg in msgs:
                self.append(len(self.logs) - 1, msg)

    def append(
        self, partition: int, msg: FeedMessage | bytes, headers: tuple[tuple[str, bytes], ...] = ()
    ) -> None:
        with self._lock:
            log = self.logs[partition]
            value = (
                msg if isinstance(msg, bytes) else msg.model_dump_json(exclude_none=True).encode()
            )
            self._clock += 1
            log.append(Record(partition, len(log), self._clock, value, headers))
            self._eof_sent.discard(partition)

    def partitions(self) -> list[int]:
        return list(range(len(self.logs))) if self.exists else []

    def watermarks(self, partition: int) -> tuple[int, int]:
        with self._lock:
            return 0, len(self.logs[partition])

    def read(self, partition: int, start: int, end: int) -> list[Record]:
        self.reads.append((partition, start, end))
        with self._lock:
            return self.logs[partition][start:end]

    def assign(self, positions: Mapping[int, int]) -> None:
        self._positions = dict(positions)
        self.assigned.set()

    def poll(self, timeout_s: float) -> list[Record | Eof]:
        with self._lock:
            items: list[Record | Eof] = []
            for p, pos in self._positions.items():
                records = self.logs[p][pos:]
                items += records
                self._positions[p] = pos + len(records)
                if p not in self._eof_sent:
                    items.append(Eof(p))
                    self._eof_sent.add(p)
        if not items:
            time.sleep(0.001)
        return items

    def close(self) -> None:
        self.closed = True


def source(broker: FakeBroker, *, scan_chunk: int = 1000) -> KafkaSource:
    def connect(config: Mapping[str, str], topic: str) -> Broker:
        assert config == {"bootstrap.servers": "kafka:9092"} and topic == TOPIC
        return broker

    return KafkaSource(
        {"bootstrap.servers": "kafka:9092"},
        TOPIC,
        connect=connect,
        scan_chunk=scan_chunk,
        retry_s=0.001,
    )


async def take(stream: AsyncIterator[FeedMessage], n: int) -> list[FeedMessage]:
    async with asyncio.timeout(5):
        return [await anext(stream) for _ in range(n)]


def start(
    match_id: int = 1, *, offset: int = 0, head: int | None = None, **at: float
) -> FeedMessage:
    period, clock_s = int(at.get("period", 1)), at.get("clock_s", 0)
    return feed_marker(
        K.match_start, offset, match_id=match_id, period=period, clock_s=clock_s, head=head
    )


def events(match_id: int, n: int, first: int = 0) -> list[FeedMessage]:
    return [
        feed_event(event(1, 10.0 * i, offset=i, id=f"m{match_id}-e{i}", match_id=match_id))
        for i in range(first, first + n)
    ]


def test_config_comes_from_kafka_variables() -> None:
    env = {
        "HOME": "/root",
        "KAFKA_BOOTSTRAP_SERVERS": "ns.servicebus.windows.net:9093",
        "KAFKA_SECURITY_PROTOCOL": "SASL_SSL",
        "KAFKA_SASL_USERNAME": "$ConnectionString",
        "KAFKA_": "ignored",
    }
    assert config_from_env(env) == {
        "bootstrap.servers": "ns.servicebus.windows.net:9093",
        "security.protocol": "SASL_SSL",
        "sasl.username": "$ConnectionString",
    }


async def test_waits_for_a_match_then_follows_it_live() -> None:
    broker = FakeBroker([])
    async with aclosing(source(broker).subscribe()) as stream:
        taken = asyncio.ensure_future(take(stream, 3))
        await asyncio.to_thread(broker.assigned.wait, 5)
        broker.append(0, start(7, head=3))  # a head meant for someone else is dropped
        for msg in events(7, 2):
            broker.append(0, msg)
        assert await taken == [start(7), *events(7, 2)]
    assert broker.closed


async def test_catches_up_with_the_match_in_progress_then_follows_it_live() -> None:
    broker = FakeBroker([start(7), *events(7, 3)])
    async with aclosing(source(broker).subscribe()) as stream:
        assert await take(stream, 4) == [start(7, head=3), *events(7, 3)]
        broker.append(0, events(7, 1, first=3)[0])
        broker.append(0, feed_marker(K.match_end, 4, match_id=7, clock_s=30))
        assert await take(stream, 2) == [
            *events(7, 1, first=3),
            feed_marker(K.match_end, 4, match_id=7, clock_s=30),
        ]


async def test_catches_up_with_a_match_that_has_only_started() -> None:
    broker = FakeBroker([start(7)])
    async with aclosing(source(broker).subscribe()) as stream:
        assert await take(stream, 1) == [start(7, head=0)]


async def test_follows_the_latest_match_looking_back_a_chunk_at_a_time() -> None:
    old = [start(1), *events(1, 4), feed_marker(K.match_end, 4, match_id=1, clock_s=30)]
    broker = FakeBroker([*old, start(2), *events(2, 3)])
    async with aclosing(source(broker, scan_chunk=2).subscribe()) as stream:
        assert await take(stream, 4) == [start(2, head=3), *events(2, 3)]
    # Read backwards from the end, two at a time, up to match 2's start.
    assert broker.reads == [(0, 8, 10), (0, 6, 8)]


async def test_follows_a_finished_match_to_its_end() -> None:
    end = feed_marker(K.match_end, 2, match_id=1, clock_s=10)
    broker = FakeBroker([start(1), *events(1, 2), end])
    async with aclosing(source(broker).subscribe()) as stream:
        assert await take(stream, 4) == [start(1, head=2), *events(1, 2), end]


async def test_follows_the_newest_match_across_partitions_and_switches_to_the_next() -> None:
    broker = FakeBroker([start(1), *events(1, 2)], [])
    broker.append(1, start(2))
    broker.append(1, events(2, 1)[0])
    async with aclosing(source(broker).subscribe()) as stream:
        assert await take(stream, 2) == [start(2, head=1), *events(2, 1)]
        broker.append(0, events(1, 1, first=2)[0])  # not the match we follow
        broker.append(0, start(3))
        broker.append(1, events(2, 1, first=1)[0])  # not any more
        broker.append(0, events(3, 1)[0])
        assert await take(stream, 2) == [start(3), *events(3, 1)]


async def test_catch_up_skips_other_matches_on_the_partition() -> None:
    broker = FakeBroker([start(1), *events(1, 1), start(2), *events(2, 2), *events(1, 1, first=1)])
    async with aclosing(source(broker).subscribe()) as stream:
        assert await take(stream, 3) == [start(2, head=2), *events(2, 2)]
        broker.append(0, events(1, 1, first=2)[0])
        broker.append(0, events(2, 1, first=2)[0])
        assert await take(stream, 1) == events(2, 1, first=2)


async def test_resumes_from_an_offset_within_the_match() -> None:
    broker = FakeBroker([start(7), *events(7, 4)])
    async with aclosing(source(broker).subscribe(from_offset=2)) as stream:
        # Picks up where event 1 (at 10s) left the match.
        assert await take(stream, 3) == [start(7, offset=2, head=4, clock_s=10), *events(7, 2, 2)]


async def test_starts_from_kick_off_when_asked_for_more_than_there_is() -> None:
    broker = FakeBroker([start(7), *events(7, 2)])
    async with aclosing(source(broker).subscribe(from_offset=5)) as stream:
        assert await take(stream, 3) == [start(7, head=2), *events(7, 2)]


async def test_waits_for_the_topic() -> None:
    broker = FakeBroker([start(7)], exists=False)
    async with aclosing(source(broker).subscribe()) as stream:
        pending = asyncio.ensure_future(take(stream, 1))
        await asyncio.sleep(0.05)
        assert not pending.done()
        broker.exists = True
        assert await pending == [start(7, head=0)]


async def test_skips_bad_messages(caplog: pytest.LogCaptureFixture) -> None:
    broker = FakeBroker([start(7), b"not json", *events(7, 1)])
    async with aclosing(source(broker).subscribe()) as stream:
        assert await take(stream, 2) == [start(7, head=1), *events(7, 1)]
        broker.append(0, b'{"schema_version": 1, "kind": "event"}')
        broker.append(0, events(7, 1, first=1)[0])
        assert await take(stream, 1) == events(7, 1, first=1)
    assert "skipping a bad message at partition 0 offset 1" in caplog.text
    assert "partition 0 offset 3: event message without its payload" in caplog.text
