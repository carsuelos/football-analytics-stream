from typing import Protocol

from engine.schema.alert_schema import Alert


class AlertSink(Protocol):
    def send(self, alert: Alert) -> None:
        """Take one alert. Returns at once and never raises: delivery is the
        sink's job, and a failure there must not stop the match."""
