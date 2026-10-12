"""Where alerts go once the detectors raise them.

An `AlertSink` takes alerts one at a time and must not block the pipeline:
anything slow, such as a network call, happens in the background.
"""

from engine.sinks.base import AlertSink
from engine.sinks.log import LogSink
from engine.sinks.webhook import WebhookSink

__all__ = ["AlertSink", "LogSink", "WebhookSink"]
