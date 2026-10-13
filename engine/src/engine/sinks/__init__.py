"""Where alerts and metric snapshots go once the engine makes them.

An `AlertSink` takes alerts one at a time, and a `MetricSink` snapshots; neither
may block the pipeline: anything slow, such as a network call, happens in the
background.
"""

from engine.sinks.base import AlertSink, MetricSink
from engine.sinks.kafka import KafkaAlertSink, KafkaMetricSink, KafkaPublisher
from engine.sinks.log import LogSink
from engine.sinks.webhook import WebhookSink

__all__ = [
    "AlertSink",
    "KafkaAlertSink",
    "KafkaMetricSink",
    "KafkaPublisher",
    "LogSink",
    "MetricSink",
    "WebhookSink",
]
