"""Match clock: where the match is, and how much play there has been."""

from dataclasses import dataclass

from engine.clock.reorder import MatchTime
from engine.schema.event_schema import EventType, MatchEvent


@dataclass(frozen=True, slots=True)
class TimedEvent:
    """An event placed on the continuous play-time axis."""

    event: MatchEvent
    play_s: float
    """Seconds of play since kick-off, with the periods joined end to end."""


class MatchClock:
    """Tracks match time from events released in order.

    It also joins the periods into one play-time axis. Each period starts where
    the previous one's last event was, stoppage time included, so the breaks
    take no play time. In the 2022 final:

        event                            match time   play time
        1st-half kick-off                P1 00:00     00:00
        last event of the 1st half       P1 52:34     52:34
        2nd-half kick-off                P2 45:00     52:34
        a minute later                   P2 46:00     53:34

    Windows measured in play time therefore run smoothly across half-time.
    """

    def __init__(self) -> None:
        self.now: MatchTime | None = None
        """Match time of the latest event, or None before the first one."""
        self.play_s = 0.0
        """Play time of the latest event."""
        self.period_start_play_s = 0.0
        """Play time at which the current period started."""
        self._period_start_clock_s = 0.0
        self.period_over = False
        """Whether the current period has ended (its half_end event), until the next one starts."""

    def advance(self, event: MatchEvent) -> TimedEvent:
        """Move the clock to the event and return it with its play time."""
        at = MatchTime.of(event)
        if self.now is not None and at < self.now:
            raise ValueError(
                f"event {event.id} at {at} is before {self.now}; "
                "events must pass through a ReorderBuffer first"
            )
        if self.now is None or at.period != self.now.period:
            self.period_start_play_s = self.play_s
            self._period_start_clock_s = at.clock_s
            self.period_over = False
        if event.type == EventType.half_end:
            self.period_over = True
        self.play_s = self.period_start_play_s + (at.clock_s - self._period_start_clock_s)
        self.now = at
        return TimedEvent(event, self.play_s)

    def reset(self) -> None:
        self.period_over = False
        self.now = None
        self.play_s = 0.0
        self.period_start_play_s = 0.0
        self._period_start_clock_s = 0.0
