"""Where windowed events live between arriving and being measured."""

from collections import deque
from typing import Protocol

from engine.clock import TimedEvent


class StateStore(Protocol):
    """Recent events per match, ordered by play time.

    Keyed by match id so a shared store (Redis, say) can hold several matches
    later. Callers append in play-time order; the store does not sort.
    """

    def append(self, match_id: int, item: TimedEvent) -> None:
        """Add the newest event of a match."""
        ...

    def query(self, match_id: int, after_play_s: float, upto_play_s: float) -> list[TimedEvent]:
        """Events with after_play_s < play_s <= upto_play_s, oldest first."""
        ...

    def evict_before(self, match_id: int, play_s: float) -> None:
        """Forget events with play_s < play_s."""
        ...

    def reset(self, match_id: int) -> None:
        """Forget everything about a match."""
        ...


class InMemoryStateStore:
    """A StateStore backed by one deque per match.

    Appends and evictions happen at the ends, so both are O(1) per event.
    Queries scan back from the newest event and stop at the window start,
    so they cost the size of the window, not of the match.
    """

    def __init__(self) -> None:
        self._matches: dict[int, deque[TimedEvent]] = {}

    def append(self, match_id: int, item: TimedEvent) -> None:
        items = self._matches.setdefault(match_id, deque())
        if items and item.play_s < items[-1].play_s:
            raise ValueError(
                f"event {item.event.id} at play {item.play_s}s is before "
                f"the newest stored event at {items[-1].play_s}s"
            )
        items.append(item)

    def query(self, match_id: int, after_play_s: float, upto_play_s: float) -> list[TimedEvent]:
        found: list[TimedEvent] = []
        for item in reversed(self._matches.get(match_id, ())):
            if item.play_s <= after_play_s:
                break
            if item.play_s <= upto_play_s:
                found.append(item)
        found.reverse()
        return found

    def evict_before(self, match_id: int, play_s: float) -> None:
        items = self._matches.get(match_id)
        while items and items[0].play_s < play_s:
            items.popleft()

    def reset(self, match_id: int) -> None:
        self._matches.pop(match_id, None)
