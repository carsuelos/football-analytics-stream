"""Where feed messages come from."""

from collections.abc import AsyncIterator
from typing import Protocol

from engine.schema.feed_schema import FeedMessage
from engine.sources.kafka import KafkaSource
from engine.sources.websocket import Backoff, WebSocketSource


class EventSource(Protocol):
    def subscribe(self, from_offset: int = 0) -> AsyncIterator[FeedMessage]:
        """Feed messages from from_offset on, as one unbroken stream."""
        ...


__all__ = ["Backoff", "EventSource", "KafkaSource", "WebSocketSource"]
