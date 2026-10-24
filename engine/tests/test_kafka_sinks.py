import asyncio
import json
import logging
from collections.abc import Mapping
from types import SimpleNamespace

import pytest
from confluent_kafka import KafkaError, KafkaException

from engine.schema.metric_schema import MetricSnapshot, TeamMetrics
from engine.sinks import KafkaAlertSink, KafkaMetricSink, KafkaPublisher
from engine.sinks.kafka import _report
from tests.factories import alert


class FakeProducer:
    """Records what is produced; a queued error is raised by the next produce."""

    def __init__(self, config: Mapping[str, str]) -> None:
        self.config = config
        self.produced: list[tuple[str, bytes, bytes]] = []
        self.headers: list[list[tuple[str, bytes]]] = []
        self.errors: list[Exception] = []
        self.polls = 0
        self.left = 0
        self.flushed: list[float] = []

    def produce(
        self, topic: str, value: bytes, key: bytes, headers: list[tuple[str, bytes]]
    ) -> None:
        if self.errors:
            raise self.errors.pop(0)
        self.produced.append((topic, key, value))
        self.headers.append(headers)

    def poll(self, timeout: float) -> int:
        self.polls += 1
        return 0

    def flush(self, timeout: float) -> int:
        self.flushed.append(timeout)
        return self.left


def publisher(**kwargs: float) -> tuple[KafkaPublisher, FakeProducer]:
    made: list[FakeProducer] = []

    def make(config: Mapping[str, str]) -> FakeProducer:
        made.append(FakeProducer(config))
        return made[0]

    p = KafkaPublisher({"bootstrap.servers": "k:9092"}, producer=make, **kwargs)
    return p, made[0]


def snapshot() -> MetricSnapshot:
    team = TeamMetrics(team_id=1, field_tilt=0.5, xt_added=0.1, xt_velocity=0.02, pressure_index=3)
    return MetricSnapshot(
        schema_version=1,
        match_id=7,
        offset=42,
        period=1,
        match_clock_s=600.0,
        window_s=300,
        teams=[team, team.model_copy(update={"team_id": 2})],
    )


async def test_sinks_publish_json_keyed_by_match() -> None:
    p, producer = publisher(drain_s=2.0)
    async with p:
        KafkaAlertSink(p).send(alert(3))
        KafkaMetricSink(p, "m").send(snapshot())
    assert producer.config == {"bootstrap.servers": "k:9092"}
    [(topic, key, value), (m_topic, m_key, m_value)] = producer.produced
    assert (topic, key, json.loads(value)["id"]) == ("alerts", b"1", "1-control_shift-2-3")
    assert (m_topic, m_key) == ("m", b"7")
    assert MetricSnapshot.model_validate_json(m_value) == snapshot()
    assert producer.flushed == [2.0]  # delivers what is queued on the way out


async def test_delivery_reports_are_served_while_running() -> None:
    p, producer = publisher(poll_s=0.01)
    async with p:
        await asyncio.sleep(0.05)
    assert producer.polls >= 3


async def test_publishing_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    p, producer = publisher()
    producer.errors = [BufferError(), KafkaException(KafkaError(KafkaError.MSG_SIZE_TOO_LARGE))]
    producer.left = 1
    sink = KafkaAlertSink(p)
    async with p:
        sink.send(alert(1))
        sink.send(alert(2))
        sink.send(alert(3))
    assert [json.loads(v)["offset"] for _, _, v in producer.produced] == [3]
    assert "kafka: queue full, dropped a message for alerts" in caplog.text
    assert "kafka: could not publish to alerts" in caplog.text
    assert "kafka: stopping with 1 messages undelivered" in caplog.text


def test_failed_deliveries_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    msg = SimpleNamespace(topic=lambda: "alerts")
    _report(None, msg)  # type: ignore[arg-type]
    assert not caplog.text
    _report(KafkaError(KafkaError._MSG_TIMED_OUT), msg)  # type: ignore[arg-type]
    assert "kafka: failed to deliver to alerts" in caplog.text
