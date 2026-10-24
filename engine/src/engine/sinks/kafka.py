"""Publishing alerts and metric snapshots to Kafka topics."""

import asyncio
import logging
from collections.abc import Callable, Mapping
from types import TracebackType
from typing import Protocol, Self

from confluent_kafka import KafkaError, KafkaException, Message
from confluent_kafka import Producer as _Producer
from opentelemetry.trace import SpanKind

from engine import telemetry
from engine.schema.alert_schema import Alert
from engine.schema.metric_schema import MetricSnapshot

log = logging.getLogger(__name__)


class Producer(Protocol):
    """What KafkaPublisher needs of a producer (confluent-kafka's, by default)."""

    def produce(
        self, topic: str, value: bytes, key: bytes, headers: list[tuple[str, bytes]]
    ) -> None:
        """Queue a message, or raise BufferError if the queue is full."""

    def poll(self, timeout: float) -> int:
        """Serve delivery reports."""

    def flush(self, timeout: float) -> int:
        """Wait for queued messages to be delivered; returns how many are left."""


class KafkaPublisher:
    """One producer for every topic the engine publishes to.

    Publishing never blocks the match: the producer queues each message and
    delivers it in the background (retrying as librdkafka does); a full queue
    drops the message with a warning, and a failed delivery is logged. Each
    message is keyed by match_id, so a match's messages stay in order on one
    partition.

    Use it as an async context manager: entering starts serving delivery
    reports, leaving delivers what is still queued, for up to drain_s.
    """

    def __init__(
        self,
        config: Mapping[str, str],
        *,
        producer: Callable[[Mapping[str, str]], Producer] | None = None,
        poll_s: float = 0.1,
        drain_s: float = 5.0,
    ) -> None:
        self._producer = (producer or ConfluentProducer)(config)
        self._poll_s = poll_s
        self._drain_s = drain_s
        self._poller: asyncio.Task[None] | None = None

    async def __aenter__(self) -> Self:
        self._poller = asyncio.create_task(self._poll())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._poller is not None:
            self._poller.cancel()
            await asyncio.wait([self._poller])
        left = await asyncio.to_thread(self._producer.flush, self._drain_s)
        if left:
            log.warning("kafka: stopping with %d messages undelivered", left)

    def publish(self, topic: str, match_id: int, value: str, *, traced: bool = False) -> None:
        """Queue value for topic. If traced, in a "send" span whose context
        goes with the message in its headers, for the consumer to continue."""
        if not traced:
            self._produce(topic, match_id, value, [])
            return
        with telemetry.tracer.start_as_current_span(
            f"send {topic}",
            kind=SpanKind.PRODUCER,
            attributes={
                "messaging.system": "kafka",
                "messaging.operation.type": "send",
                "messaging.destination.name": topic,
                "messaging.kafka.message.key": str(match_id),
            },
        ):
            self._produce(topic, match_id, value, telemetry.inject())

    def _produce(
        self, topic: str, match_id: int, value: str, headers: list[tuple[str, bytes]]
    ) -> None:
        try:
            self._producer.produce(topic, value.encode(), str(match_id).encode(), headers)
        except BufferError:
            log.warning("kafka: queue full, dropped a message for %s", topic)
        except KafkaException as e:
            log.warning("kafka: could not publish to %s: %s", topic, e)

    async def _poll(self) -> None:
        while True:
            self._producer.poll(0)
            await asyncio.sleep(self._poll_s)


class KafkaAlertSink:
    """An AlertSink that publishes each alert, as JSON, to a topic."""

    def __init__(self, publisher: KafkaPublisher, topic: str = "alerts") -> None:
        self.publisher = publisher
        self.topic = topic

    def send(self, alert: Alert) -> None:
        self.publisher.publish(self.topic, alert.match_id, alert.model_dump_json(), traced=True)


class KafkaMetricSink:
    """A MetricSink that publishes each snapshot, as JSON, to a topic."""

    def __init__(self, publisher: KafkaPublisher, topic: str = "metrics") -> None:
        self.publisher = publisher
        self.topic = topic

    def send(self, snapshot: MetricSnapshot) -> None:
        self.publisher.publish(self.topic, snapshot.match_id, snapshot.model_dump_json())


class ConfluentProducer:
    """confluent-kafka's producer, idempotent, logging failed deliveries."""

    def __init__(self, config: Mapping[str, str]) -> None:
        self._producer = _Producer(
            {"client.id": "engine", "enable.idempotence": True, "linger.ms": 5, **config}
        )

    def produce(
        self, topic: str, value: bytes, key: bytes, headers: list[tuple[str, bytes]]
    ) -> None:
        self._producer.produce(
            topic,
            value,
            key,
            headers=list[tuple[str, str | bytes | None]](headers) or None,
            on_delivery=_report,
        )

    def poll(self, timeout: float) -> int:
        return self._producer.poll(timeout)

    def flush(self, timeout: float) -> int:
        return self._producer.flush(timeout)


def _report(error: KafkaError | None, msg: Message) -> None:
    if error is not None:
        log.warning("kafka: failed to deliver to %s: %s", msg.topic(), error)
