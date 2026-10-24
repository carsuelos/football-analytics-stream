"""KafkaSource's Broker over confluent-kafka (librdkafka)."""

import logging
from collections.abc import Mapping

from confluent_kafka import Consumer, KafkaError, KafkaException, Message, TopicPartition

from engine.sources.kafka import Eof, Record

log = logging.getLogger(__name__)

BATCH = 500
TIMEOUT_S = 10.0


class ConfluentBroker:
    """A consumer assigned to partitions of one topic by hand.

    It joins no consumer group and commits nothing: the engine always finds its
    own place on the topic (see KafkaSource), so a group id is only a label.
    """

    def __init__(self, config: Mapping[str, str], topic: str) -> None:
        self._topic = topic
        self._consumer = Consumer(
            {
                "client.id": "engine",
                "group.id": "engine",
                "enable.auto.commit": False,
                "enable.partition.eof": True,
                # If retention has removed where we were, start at the oldest.
                "auto.offset.reset": "earliest",
                **config,
            }
        )

    def partitions(self) -> list[int]:
        topic = self._consumer.list_topics(self._topic, timeout=TIMEOUT_S).topics.get(self._topic)
        if topic is None or topic.error is not None:
            return []
        return sorted(topic.partitions)

    def watermarks(self, partition: int) -> tuple[int, int]:
        low, high = self._consumer.get_watermark_offsets(
            TopicPartition(self._topic, partition), timeout=TIMEOUT_S
        )
        return low, high

    def read(self, partition: int, start: int, end: int) -> list[Record]:
        self.assign({partition: start})
        records: list[Record] = []
        while True:
            for item in self.poll(TIMEOUT_S):
                if isinstance(item, Eof):
                    return records
                if item.offset >= end:
                    return records
                records.append(item)
                if item.offset >= end - 1:
                    return records

    def assign(self, positions: Mapping[int, int]) -> None:
        self._consumer.assign(
            [TopicPartition(self._topic, p, offset) for p, offset in positions.items()]
        )

    def poll(self, timeout_s: float) -> list[Record | Eof]:
        # Wait for the first message only, then take what has already arrived:
        # consume() alone would wait out the whole timeout for a full batch,
        # holding each live event back by up to timeout_s.
        first = self._consumer.poll(timeout_s)
        if first is None:
            return []
        items: list[Record | Eof] = []
        for msg in [first, *self._consumer.consume(BATCH - 1, timeout=0)]:
            if item := _item(msg):
                items.append(item)
        return items

    def close(self) -> None:
        self._consumer.close()


def _item(msg: Message) -> Record | Eof | None:
    error = msg.error()
    partition = msg.partition()
    if partition is None:
        partition = -1
    if error is None:
        offset = msg.offset()
        _, timestamp_ms = msg.timestamp()
        return Record(
            partition,
            -1 if offset is None else offset,
            timestamp_ms,
            msg.value() or b"",
            _headers(msg),
        )
    if error.code() == KafkaError._PARTITION_EOF:
        return Eof(partition)
    if error.fatal():
        raise KafkaException(error)
    # Most errors are transient (a broker restarting, say); librdkafka retries.
    log.warning("kafka: %s", error)
    return None


def _headers(msg: Message) -> tuple[tuple[str, bytes], ...]:
    """The message's headers as (name, bytes) pairs."""
    raw = msg.headers() or []
    pairs = raw.items() if isinstance(raw, dict) else raw
    return tuple((k, v.encode() if isinstance(v, str) else v or b"") for k, v in pairs)
