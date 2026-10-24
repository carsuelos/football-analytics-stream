import json
import logging
from contextlib import aclosing

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from engine import telemetry
from engine.sinks.kafka import KafkaAlertSink, KafkaPublisher
from tests.factories import alert, event
from tests.test_kafka_sinks import FakeProducer
from tests.test_kafka_source import FakeBroker, events, source, start, take

# The global provider can be set once a process: these tests' spans, and any
# other test's, go to EXPORTER.
EXPORTER = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(EXPORTER))
trace.set_tracer_provider(_provider)

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
SIMULATOR_SPAN = "00f067aa0ba902b7"
TRACEPARENT = f"00-{TRACE_ID}-{SIMULATOR_SPAN}-01".encode()


@pytest.fixture(autouse=True)
def fresh() -> None:
    EXPORTER.clear()
    telemetry.events.clear()


def ended(name: str) -> ReadableSpan:
    [span] = [s for s in EXPORTER.get_finished_spans() if s.name == name]
    return span


def ids(span: ReadableSpan) -> tuple[str, str, str | None]:
    """The span's trace id, span id and parent's span id, in hex."""
    assert span.context is not None
    parent = format(span.parent.span_id, "016x") if span.parent else None
    return format(span.context.trace_id, "032x"), format(span.context.span_id, "016x"), parent


def test_tracing_is_off_without_an_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not telemetry.tracing_enabled({})
    assert telemetry.tracing_enabled({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://aspire:18889"})
    assert telemetry.tracing_enabled({"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://x:4317"})
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    telemetry.configure_tracing()()  # nothing to set up or flush


def test_json_logs_carry_the_span() -> None:
    formatter = telemetry.JsonFormatter()

    def line(msg: str) -> dict[str, object]:
        record = logging.LogRecord("engine.x", logging.INFO, __file__, 1, msg, (), None)
        parsed: dict[str, object] = json.loads(formatter.format(record))
        return parsed

    with telemetry.tracer.start_as_current_span("work") as span:
        inside = line("in a span: é")
    outside = line("outside")
    context = span.get_span_context()
    assert inside["msg"] == "in a span: é" and inside["level"] == "INFO"
    assert inside["logger"] == "engine.x"
    assert inside["trace_id"] == format(context.trace_id, "032x")
    assert inside["span_id"] == format(context.span_id, "016x")
    assert "trace_id" not in outside


def test_configure_logging_writes_json_or_text(capsys: pytest.CaptureFixture[str]) -> None:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    try:
        telemetry.configure_logging("INFO", "json")
        logging.getLogger("engine.x").info("hello %d", 1)
        assert json.loads(capsys.readouterr().err)["msg"] == "hello 1"
        telemetry.configure_logging("INFO", "")
        logging.getLogger("engine.x").info("hello %d", 2)
        assert capsys.readouterr().err.rstrip().endswith("INFO    hello 2")
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)


async def test_live_events_continue_the_simulators_trace() -> None:
    broker = FakeBroker([start(7), *events(7, 1)])
    async with aclosing(source(broker).subscribe()) as stream:
        await take(stream, 2)  # caught up: no spans for what happened before
        [e1] = events(7, 1, first=1)
        broker.append(0, e1, (("traceparent", TRACEPARENT), ("other", b"x")))
        assert await take(stream, 1) == [e1]
    receive = ended("receive events")
    assert receive.kind is SpanKind.CONSUMER
    assert ids(receive)[0] == TRACE_ID and ids(receive)[2] == SIMULATOR_SPAN
    assert receive.attributes is not None
    assert (
        receive.attributes["event.offset"] == 1
        and receive.attributes["messaging.kafka.offset"] == 2
    )
    assert [s.name for s in EXPORTER.get_finished_spans()] == ["receive events"]


def test_an_alert_joins_the_trace_of_the_event_that_raised_it() -> None:
    raised_by = event(2, 4947, offset=12, match_id=3869685)
    telemetry.received(raised_by, [("traceparent", TRACEPARENT)], "events", 0, 99)
    producer = FakeProducer({})
    sink = KafkaAlertSink(KafkaPublisher({}, producer=lambda _: producer))
    with telemetry.raising(alert(), raised_by):
        sink.send(alert())
    sink.publisher.publish("metrics", 1, "{}")  # untraced

    receive, raise_, send = (
        ended("receive events"),
        ended("alert control_shift"),
        ended("send alerts"),
    )
    assert {ids(s)[0] for s in (receive, raise_, send)} == {TRACE_ID}
    assert ids(raise_)[2] == ids(receive)[1] and ids(send)[2] == ids(raise_)[1]
    assert send.kind is SpanKind.PRODUCER
    [alert_headers, metric_headers] = producer.headers
    assert dict(alert_headers)["traceparent"] == f"00-{TRACE_ID}-{ids(send)[1]}-01".encode()
    assert metric_headers == []


def test_an_alert_with_no_received_event_starts_a_trace() -> None:
    with telemetry.raising(alert(), event(2, 4947, offset=12)):
        pass
    assert ended("alert control_shift").parent is None


def test_only_recent_events_are_remembered() -> None:
    traces = telemetry.EventTraces(size=2)
    with telemetry.tracer.start_as_current_span("x") as span:
        for i in range(3):
            traces.remember(event(1, i, offset=i), span.get_span_context())
    assert traces.context_for(event(1, 0, offset=0)) is None
    assert traces.context_for(event(1, 2, offset=2)) is not None
