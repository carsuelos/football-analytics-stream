"""Reorder buffer with a watermark: put slightly late events back in order."""

import heapq
import logging
from dataclasses import dataclass
from typing import NamedTuple, Self

from engine.schema.event_schema import MatchEvent

log = logging.getLogger(__name__)


class MatchTime(NamedTuple):
    """A point in match time.

    Clocks overlap across periods because of stoppage time (the first half can
    run to 52:00, the second half starts at 45:00), so a clock alone can't be
    compared. Tuples compare element by element, so ordering by period first
    and then clock comes for free.
    """

    period: int
    clock_s: float

    @classmethod
    def of(cls, event: MatchEvent) -> Self:
        return cls(event.period, event.match_clock_s)

    def __str__(self) -> str:
        minutes, seconds = divmod(int(self.clock_s), 60)
        return f"P{self.period} {minutes:02d}:{seconds:02d}"


@dataclass
class ReorderStats:
    released: int = 0
    duplicates: int = 0
    late_dropped: int = 0


class ReorderBuffer:
    """Releases events in match-time order once the watermark has passed them.

    The watermark trails the latest match time seen so far by
    `allowed_lateness_s`. Events are held until the watermark reaches them, so
    anything up to that late still comes out in order. An event that arrives
    behind the watermark has missed its slot: it is dropped and counted.

    The watermark never reaches back into an earlier period, so the first event
    of a new period releases everything left from the previous one.

    When the feed goes quiet (a goal, a VAR check, a set piece), nothing moves
    the watermark on, so the last events would wait for the next one, possibly
    minutes later. release_all lets them out after a pause (Pipeline.release_idle);
    the watermark then stays at least at the latest released, so the order holds.
    """

    def __init__(self, allowed_lateness_s: float) -> None:
        if allowed_lateness_s < 0:
            raise ValueError("allowed_lateness_s must not be negative")
        self.allowed_lateness_s = allowed_lateness_s
        self.stats = ReorderStats()
        # A min-heap ordered by match time. Offsets are unique within a match,
        # so ties are broken by arrival order and events are never compared.
        self._heap: list[tuple[MatchTime, int, MatchEvent]] = []
        self._seen: set[str] = set()
        self._latest: MatchTime | None = None
        self._released_to: MatchTime | None = None

    def __len__(self) -> int:
        """The number of events waiting for the watermark."""
        return len(self._heap)

    @property
    def watermark(self) -> MatchTime | None:
        """Every event at or before this time has been released."""
        if self._latest is None:
            return None
        trailing = MatchTime(self._latest.period, self._latest.clock_s - self.allowed_lateness_s)
        if self._released_to is not None and self._released_to > trailing:
            return self._released_to
        return trailing

    def push(self, event: MatchEvent) -> list[MatchEvent]:
        """Add an event, and return the events it lets through, in order."""
        if event.id in self._seen:
            self.stats.duplicates += 1
            return []
        self._seen.add(event.id)

        at = MatchTime.of(event)
        watermark = self.watermark
        if watermark is not None and at < watermark:
            self.stats.late_dropped += 1
            log.warning(
                "dropped late event %s (offset %d) at %s; watermark is %s",
                event.id,
                event.offset,
                at,
                watermark,
            )
            return []

        heapq.heappush(self._heap, (at, event.offset, event))
        if self._latest is None or at > self._latest:
            self._latest = at
        return self._release(self.watermark)

    def flush(self) -> list[MatchEvent]:
        """Release everything still held, e.g. when the match ends."""
        return self._release(None)

    def release_all(self) -> list[MatchEvent]:
        """Release everything held now, the feed having gone quiet, and from
        then on drop anything earlier than it as late, as the watermark would."""
        released = self._release(None)
        if released:
            self._released_to = MatchTime.of(released[-1])
        return released

    def reset(self) -> None:
        """Forget everything, e.g. before the feed replays after a seek."""
        self.stats = ReorderStats()
        self._heap.clear()
        self._seen.clear()
        self._latest = None
        self._released_to = None

    def _release(self, upto: MatchTime | None) -> list[MatchEvent]:
        released: list[MatchEvent] = []
        while self._heap and (upto is None or self._heap[0][0] <= upto):
            released.append(heapq.heappop(self._heap)[2])
        self.stats.released += len(released)
        return released
