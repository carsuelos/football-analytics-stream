"""Turn the raw feed into an ordered stream in match time.

The feed can repeat events and deliver some slightly late. `ReorderBuffer` drops
the repeats, holds events back until the watermark passes them and releases
them in match-time order. `MatchClock` then puts each released event on a
single continuous play-time axis, which the windows use.
"""

from engine.clock.reorder import MatchTime, ReorderBuffer, ReorderStats
from engine.clock.tracker import MatchClock, TimedEvent

__all__ = ["MatchClock", "MatchTime", "ReorderBuffer", "ReorderStats", "TimedEvent"]
