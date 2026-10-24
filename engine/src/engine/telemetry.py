"""Logging and tracing, set up the same way as in the Go apps.

Logs go to stderr, as text or (with LOG_FORMAT=json) one JSON object a line,
which is what log collectors such as Azure's expect. A record logged inside a
span carries the span's trace_id and span_id, so logs and traces can be joined.

Tracing is off unless OTEL_EXPORTER_OTLP_ENDPOINT is set. Then spans are
exported over OTLP/gRPC, configured by the standard OTEL_* variables
(OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES, OTEL_TRACES_SAMPLER, ...), and
trace context travels in W3C traceparent headers, over HTTP and in Kafka
message headers. Nothing here is specific to a vendor: locally the spans go to
the Aspire dashboard, in Azure to the Container Apps OpenTelemetry agent, which
forwards them to Application Insights.

What is traced, from the simulator's "send events" span on:

  - "receive events": each live event read from Kafka, continuing the
    simulator's trace from the message's headers;
  - "alert <type>": raising an alert, under the receive span of the event that
    completed the tick, then "send alerts" as it goes to Kafka (where the
    notifier picks the trace up) and any webhook requests;
  - the API's requests, and its calls to the simulator.
"""

import json
import logging
import os
from collections import OrderedDict
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime

from opentelemetry import propagate, trace
from opentelemetry.context import Context
from opentelemetry.trace import NonRecordingSpan, Span, SpanContext, SpanKind

from engine.schema.alert_schema import Alert
from engine.schema.event_schema import MatchEvent

tracer = trace.get_tracer("engine")

type Headers = Sequence[tuple[str, bytes]]


def tracing_enabled(environ: Mapping[str, str] = os.environ) -> bool:
    """Whether the environment asks for traces to be exported."""
    return bool(
        environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        or environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    )


def configure_tracing(service: str = "engine") -> Callable[[], None]:
    """Export spans over OTLP if tracing_enabled; returns what to call on the
    way out to send what is buffered. OTEL_SERVICE_NAME and a service.name in
    OTEL_RESOURCE_ATTRIBUTES take precedence over service."""
    if not tracing_enabled():
        return lambda: None
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    named = os.environ.get("OTEL_SERVICE_NAME") or "service.name=" in os.environ.get(
        "OTEL_RESOURCE_ATTRIBUTES", ""
    )
    provider = TracerProvider(resource=Resource.create({} if named else {"service.name": service}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    return provider.shutdown


class JsonFormatter(logging.Formatter):
    """One JSON object a line: time, level, logger and message, the span's
    trace_id and span_id if there is one, and the exception if any."""

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            line["trace_id"] = format(context.trace_id, "032x")
            line["span_id"] = format(context.span_id, "016x")
        if record.exc_info:
            line["exc"] = self.formatException(record.exc_info)
        return json.dumps(line, ensure_ascii=False)


def configure_logging(level: str, fmt: str | None = None) -> None:
    """Log to stderr at level: as JSON if fmt (default: LOG_FORMAT) is "json",
    else as text."""
    fmt = fmt if fmt is not None else os.environ.get("LOG_FORMAT", "")
    handler = logging.StreamHandler()
    if fmt.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
        )
    logging.basicConfig(level=level, handlers=[handler], force=True)


def inject() -> list[tuple[str, bytes]]:
    """The current trace context, as Kafka message headers."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return [(k, v.encode()) for k, v in carrier.items()]


def extract(headers: Headers) -> Context:
    """The trace context in Kafka message headers."""
    return propagate.extract({k: v.decode(errors="replace") for k, v in headers})


class EventTraces:
    """The span each recent live event was received in, so the alert an event
    raises joins its trace. Keeps the last size events."""

    def __init__(self, size: int = 10_000) -> None:
        self._size = size
        self._spans: OrderedDict[tuple[int, int], SpanContext] = OrderedDict()

    def remember(self, event: MatchEvent, context: SpanContext) -> None:
        if not context.is_valid:
            return
        self._spans[(event.match_id, event.offset)] = context
        if len(self._spans) > self._size:
            self._spans.popitem(last=False)

    def context_for(self, event: MatchEvent) -> Context | None:
        span = self._spans.get((event.match_id, event.offset))
        return trace.set_span_in_context(NonRecordingSpan(span)) if span else None

    def clear(self) -> None:
        self._spans.clear()


events = EventTraces()
"""The engine's one record of received events' spans."""


def received(event: MatchEvent, headers: Headers, topic: str, partition: int, offset: int) -> None:
    """Record an event read from Kafka as a span in the sender's trace (a new
    one if its headers have no trace context)."""
    with tracer.start_as_current_span(
        f"receive {topic}",
        context=extract(headers),
        kind=SpanKind.CONSUMER,
        attributes={
            "messaging.system": "kafka",
            "messaging.operation.type": "receive",
            "messaging.destination.name": topic,
            "messaging.destination.partition.id": str(partition),
            "messaging.kafka.offset": offset,
            "match.id": event.match_id,
            "event.offset": event.offset,
            "event.type": event.type.value,
        },
    ) as span:
        events.remember(event, span.get_span_context())


@contextmanager
def raising(alert: Alert, event: MatchEvent) -> Iterator[Span]:
    """A span for sending alert out, under the receive span of the event that
    raised it, if it was received recently."""
    with tracer.start_as_current_span(
        f"alert {alert.type.value}",
        context=events.context_for(event),
        attributes={
            "alert.id": alert.id,
            "alert.type": alert.type.value,
            "alert.team_id": alert.team_id,
            "alert.value": alert.value,
            "match.id": alert.match_id,
        },
    ) as span:
        yield span
