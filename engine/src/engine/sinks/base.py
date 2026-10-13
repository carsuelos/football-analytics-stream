from typing import Protocol

from engine.schema.alert_schema import Alert
from engine.schema.metric_schema import MetricSnapshot


class AlertSink(Protocol):
    def send(self, alert: Alert) -> None:
        """Take one alert. Returns at once and never raises: delivery is the
        sink's job, and a failure there must not stop the match."""


class MetricSink(Protocol):
    def send(self, snapshot: MetricSnapshot) -> None:
        """Take one metric snapshot. Returns at once and never raises, like
        AlertSink.send."""
