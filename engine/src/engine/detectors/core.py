"""Run detectors on a fixed play-time tick and turn their signals into alerts."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from engine.clock import TimedEvent
from engine.metrics import MetricsConfig
from engine.pipeline import Pipeline
from engine.schema.alert_schema import Alert, AlertType
from engine.schema.common_schema import Team
from engine.schema.event_schema import MatchEvent
from engine.windows import SlidingWindows

SHOOTOUT_PERIOD = 5


@dataclass(frozen=True)
class DetectorConfig:
    tick_s: float = 30.0
    """Detectors run once per tick_s seconds of play."""
    cooldown_s: float = 300.0
    """After an alert, the same detector stays quiet for the same team this long."""


@dataclass(frozen=True)
class Tick:
    """What a detector sees when it runs: the match as of one event."""

    item: TimedEvent
    """The first event past the tick boundary, and the latest in the windows."""
    windows: SlidingWindows
    team_ids: tuple[int, int]
    teams: dict[int, Team]
    metrics: MetricsConfig

    @property
    def play_s(self) -> float:
        return self.item.play_s

    def events(self, length_s: float) -> list[MatchEvent]:
        """Events in the window of length_s ending now, in match-time order."""
        return [i.event for i in self.windows.events(length_s)]


@dataclass(frozen=True)
class Signal:
    """A detector's finding for one team, before cooldown and replay checks."""

    team_id: int
    value: float
    threshold: float
    window_s: float
    features: dict[str, float]
    message: str


class Detector(Protocol):
    type: AlertType

    def reset(self) -> None:
        """Forget everything: the match is starting over."""

    def evaluate(self, tick: Tick) -> list[Signal]:
        """Update state with the match as of tick; return any signals.

        Called on every tick, replays included, so state such as baselines is
        the same after a seek as it would have been live.
        """
        ...


class Detectors:
    """Runs detectors once per tick of play and turns their signals into alerts.

    A tick is the first released event at or past each multiple of tick_s of
    play time. The penalty shootout is not play, so it has no ticks.

    Signals are rate-limited per (detector, team) by the cooldown. During a
    replay or catch-up the detectors still run and the cooldowns still apply,
    but no alerts come out: the alerts after a seek are then exactly those
    that would have come out live.
    """

    def __init__(
        self,
        detectors: Sequence[Detector],
        metrics: MetricsConfig,
        config: DetectorConfig | None = None,
    ) -> None:
        self.detectors = list(detectors)
        self.metrics = metrics
        self.config = config or DetectorConfig()
        self._generation = -1
        self._last_tick = 0
        self._last_alert_s: dict[tuple[AlertType, int], float] = {}

    def observe(self, pipeline: Pipeline, item: TimedEvent) -> list[Alert]:
        """Take one event released by pipeline; return the alerts it raises."""
        if pipeline.generation != self._generation:
            self._reset(pipeline.generation)
        if item.event.period == SHOOTOUT_PERIOD:
            return []
        tick = int(item.play_s // self.config.tick_s)
        if tick <= self._last_tick:
            return []
        self._last_tick = tick
        if pipeline.windows is None or pipeline.team_ids is None:
            return []
        now = Tick(item, pipeline.windows, pipeline.team_ids, pipeline.teams, self.metrics)
        replay = pipeline.is_replay(item)
        alerts = []
        for detector in self.detectors:
            for signal in detector.evaluate(now):
                key = (detector.type, signal.team_id)
                last_s = self._last_alert_s.get(key)
                if last_s is not None and item.play_s - last_s < self.config.cooldown_s:
                    continue
                self._last_alert_s[key] = item.play_s
                if not replay:
                    alerts.append(_alert(detector.type, signal, item.event))
        return alerts

    def _reset(self, generation: int) -> None:
        self._generation = generation
        self._last_tick = 0
        self._last_alert_s = {}
        for detector in self.detectors:
            detector.reset()


def _alert(type: AlertType, signal: Signal, at: MatchEvent) -> Alert:
    return Alert(
        schema_version=1,
        # The same alert gets the same id when a match is replayed.
        id=f"{at.match_id}-{type}-{signal.team_id}-{at.offset}",
        match_id=at.match_id,
        offset=at.offset,
        period=at.period,
        match_clock_s=at.match_clock_s,
        type=type,
        team_id=signal.team_id,
        value=signal.value,
        threshold=signal.threshold,
        window_s=round(signal.window_s),
        features=signal.features,
        message=signal.message,
    )
