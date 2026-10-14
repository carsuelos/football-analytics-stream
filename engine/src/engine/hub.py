"""The match hub: the current match's history, and live updates to subscribers."""

import asyncio
import logging
from collections.abc import AsyncGenerator

from engine.schema.alert_schema import Alert
from engine.schema.engine_status_schema import EngineStatus
from engine.schema.incident_schema import Incident
from engine.schema.match_reset_schema import MatchReset
from engine.schema.metric_schema import MetricSnapshot

log = logging.getLogger(__name__)

type Update = MatchReset | EngineStatus | MetricSnapshot | Alert | Incident
type MatchUpdate = MetricSnapshot | Alert | Incident


class MatchHub:
    """Keeps the current match's history and fans updates out to subscribers.

    The history is everything since the last reset: metric snapshots, alerts
    and incidents, in the order they happened. A new subscriber gets the
    reset, the latest status and the history, then every update as it
    happens. So a subscriber that (re)connects mid-match has the whole match.

    Each subscriber has a queue of at most max_pending updates. One that falls
    that far behind is dropped rather than holding up the engine or memory: its
    stream ends, and when it reconnects it gets the full history again. The
    default is several times a whole match's history, so the burst of updates
    from a seek's rebuild never trips it; only a stuck subscriber does.
    """

    def __init__(self, max_pending: int = 20_000) -> None:
        self.max_pending = max_pending
        self.reset = MatchReset(schema_version=1, generation=0)
        self.status: EngineStatus | None = None
        self.snapshots: list[MetricSnapshot] = []
        self.alerts: list[Alert] = []
        self.incidents: list[Incident] = []
        self._history: list[MatchUpdate] = []
        self._subscribers: set[asyncio.Queue[Update]] = set()
        self._closed = False

    @property
    def generation(self) -> int:
        return self.reset.generation

    @property
    def subscribers(self) -> int:
        return len(self._subscribers)

    def start(self, generation: int, match_id: int | None) -> None:
        """Start the history over, and tell subscribers to do the same."""
        self.reset = MatchReset(schema_version=1, generation=generation, match_id=match_id)
        self.status = None
        self.snapshots, self.alerts, self.incidents, self._history = [], [], [], []
        self._publish(self.reset)

    def set_status(self, status: EngineStatus) -> None:
        """Publish status, unless it is unchanged."""
        if status != self.status:
            self.status = status
            self._publish(status)

    def add(self, *updates: MatchUpdate) -> None:
        """Add snapshots, alerts and incidents to the history, and publish them."""
        for update in updates:
            match update:
                case MetricSnapshot():
                    self.snapshots.append(update)
                case Alert():
                    self.alerts.append(update)
                case Incident():
                    self.incidents.append(update)
            self._history.append(update)
            self._publish(update)

    def close(self) -> None:
        """End every subscriber's stream, and any later one's at once (e.g. on shutdown)."""
        self._closed = True
        for queue in self._subscribers:
            queue.shutdown(immediate=True)
        self._subscribers.clear()

    async def subscribe(self) -> AsyncGenerator[Update]:
        """The reset, the latest status and the history, then updates as they happen.

        Ends if the subscriber falls max_pending updates behind, or the hub is
        closed. Close it when done (e.g. with contextlib.aclosing) so the hub
        stops queueing for it.
        """
        if self._closed:
            return
        queue: asyncio.Queue[Update] = asyncio.Queue(self.max_pending)
        # No await between taking the backlog and registering the queue, so no
        # update can fall between the two.
        backlog: list[Update] = [
            self.reset,
            *([self.status] if self.status else []),
            *self._history,
        ]
        self._subscribers.add(queue)
        try:
            for update in backlog:
                yield update
            while True:
                try:
                    yield await queue.get()
                except asyncio.QueueShutDown:
                    return
        finally:
            self._subscribers.discard(queue)

    def _publish(self, update: Update) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(update)
            except asyncio.QueueFull:
                log.warning("dropping a subscriber %d updates behind", self.max_pending)
                queue.shutdown(immediate=True)
                self._subscribers.discard(queue)
