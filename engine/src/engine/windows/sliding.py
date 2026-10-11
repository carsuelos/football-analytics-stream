"""Sliding windows over the play-time axis."""

from enum import StrEnum

from engine.clock import MatchTime, TimedEvent
from engine.windows.store import StateStore

FIVE_MINUTES_S = 300.0
TEN_MINUTES_S = 600.0
SHOOTOUT_PERIOD = 5


class WindowMode(StrEnum):
    CONTINUOUS = "continuous"
    """Windows run across half-time: the last 5 minutes of play, whatever the period."""
    PER_PERIOD = "per_period"
    """Windows restart at each kick-off: the last 5 minutes of play in this period."""


class SlidingWindows:
    """The last N seconds of play for one match, for each window length.

    Windows end at the newest event added, the match's "now", so they move
    in match time and give the same answer at any playback speed.

    Penalty shootout events are ignored: a shootout isn't open play, so the
    windows stay as they were at the end of extra time.
    """

    def __init__(
        self,
        store: StateStore,
        match_id: int,
        *,
        lengths_s: tuple[float, ...] = (FIVE_MINUTES_S, TEN_MINUTES_S),
        mode: WindowMode = WindowMode.CONTINUOUS,
    ) -> None:
        if not lengths_s or min(lengths_s) <= 0:
            raise ValueError(f"window lengths must be positive, got {lengths_s}")
        self.store = store
        self.match_id = match_id
        self.lengths_s = lengths_s
        self.mode = mode
        self._now: TimedEvent | None = None

    @property
    def now(self) -> MatchTime | None:
        """Match time of the newest event in the windows."""
        return MatchTime.of(self._now.event) if self._now else None

    def add(self, item: TimedEvent) -> None:
        """Slide the windows forward to include an event."""
        if item.event.period == SHOOTOUT_PERIOD:
            return
        self.store.append(self.match_id, item)
        self._now = item
        self.store.evict_before(self.match_id, item.play_s - max(self.lengths_s))

    def events(self, length_s: float) -> list[TimedEvent]:
        """Events in the last length_s seconds of play, oldest first."""
        if length_s > max(self.lengths_s):
            raise ValueError(
                f"{length_s}s is longer than the longest window kept ({max(self.lengths_s)}s)"
            )
        if self._now is None:
            return []
        end = self._now.play_s
        items = self.store.query(self.match_id, end - length_s, end)
        if self.mode is WindowMode.PER_PERIOD:
            # Filter on period, not play time: a period's last event and the
            # next kick-off share the same play time.
            period = self._now.event.period
            items = [i for i in items if i.event.period == period]
        return items

    def reset(self) -> None:
        self.store.reset(self.match_id)
        self._now = None
