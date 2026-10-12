import logging

from engine.clock import MatchTime
from engine.schema.alert_schema import Alert

log = logging.getLogger(__name__)


class LogSink:
    """Writes each alert as one log line."""

    def __init__(self, logger: logging.Logger = log) -> None:
        self.logger = logger

    def send(self, alert: Alert) -> None:
        at = MatchTime(alert.period, alert.match_clock_s)
        self.logger.info("ALERT %s %s: %s", at, alert.type, alert.message)
