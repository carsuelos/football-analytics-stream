"""Ticks: the fixed points in play time at which the engine takes stock.

Detectors run and metric snapshots are taken once per tick, so both are a
function of match time alone: identical at any playback speed and after a seek.
"""

from dataclasses import dataclass

from engine.clock import TimedEvent
from engine.metrics import MetricsConfig, snapshot
from engine.pipeline import Pipeline
from engine.schema.common_schema import Team
from engine.schema.event_schema import MatchEvent
from engine.schema.metric_schema import MetricSnapshot
from engine.windows import SlidingWindows

SHOOTOUT_PERIOD = 5

TICK_S = 5.0
"""The live engine's tick. The detectors and features are functions of play
time, not of how often they run, so a finer tick only lets an alert fire
sooner after the play that raised it (and the charts move more often). The
goal model is trained on 30s ticks (see model.dataset): a subset of these, as
each tick is the first event at or past a multiple of the tick."""


@dataclass(frozen=True)
class Tick:
    """The match as of one event.

    A tick is a view of the pipeline, not a copy: use it before the pipeline
    handles its next message.
    """

    item: TimedEvent
    """The first event past the tick boundary, and the latest in the windows."""
    windows: SlidingWindows
    team_ids: tuple[int, int]
    teams: dict[int, Team]
    metrics: MetricsConfig
    generation: int = 0
    """The pipeline generation: when it changes, the match has started over."""
    replay: bool = False
    """Whether the event is being replayed (after a seek, or caught up on after
    connecting mid-match) rather than happening live."""

    @property
    def play_s(self) -> float:
        return self.item.play_s

    def events(self, length_s: float) -> list[MatchEvent]:
        """Events in the window of length_s ending now, in match-time order."""
        return [i.event for i in self.windows.events(length_s)]

    def snapshots(self) -> list[MetricSnapshot]:
        """Every metric for both teams, over each window."""
        return [
            s
            for length_s in self.windows.lengths_s
            if (s := snapshot(self.windows, length_s, self.team_ids, self.metrics))
        ]


class Ticker:
    """Picks the ticks out of the events a pipeline releases.

    A tick is the first released event at or past each multiple of tick_s of
    play time, once both teams have appeared. The penalty shootout is not
    play, so it has no ticks. When the pipeline starts over, so do the ticks.
    """

    def __init__(self, metrics: MetricsConfig, tick_s: float = TICK_S) -> None:
        self.metrics = metrics
        self.tick_s = tick_s
        self._generation = -1
        self._last_tick = 0

    def observe(self, pipeline: Pipeline, item: TimedEvent) -> Tick | None:
        """Take one event released by pipeline; return a Tick if it is one."""
        if pipeline.generation != self._generation:
            self._generation = pipeline.generation
            self._last_tick = 0
        if item.event.period == SHOOTOUT_PERIOD:
            return None
        n = int(item.play_s // self.tick_s)
        if n <= self._last_tick:
            return None
        self._last_tick = n
        if pipeline.windows is None or pipeline.team_ids is None:
            return None
        return Tick(
            item,
            pipeline.windows,
            pipeline.team_ids,
            pipeline.teams,
            self.metrics,
            generation=pipeline.generation,
            replay=pipeline.is_replay(item),
        )
