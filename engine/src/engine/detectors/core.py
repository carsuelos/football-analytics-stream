"""Run detectors on each tick and turn their signals into alerts."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from engine.schema.alert_schema import Alert, AlertType
from engine.schema.event_schema import MatchEvent
from engine.ticks import Tick


@dataclass(frozen=True)
class DetectorConfig:
    cooldown_s: float = 300.0
    """After an alert, the same detector stays quiet for the same team this long."""


@dataclass(frozen=True)
class Signal:
    """A detector's finding for one team, before the cooldown."""

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
    """Runs detectors on each tick and turns their signals into alerts.

    Signals are rate-limited per (detector, team) by the cooldown. Replayed
    ticks raise alerts too, exactly as they did live, so a seek rebuilds the
    match's alerts along with its metrics. Deciding who hears about a replayed
    alert is the caller's job (see `Tick.replay`).
    """

    def __init__(self, detectors: Sequence[Detector], config: DetectorConfig | None = None) -> None:
        self.detectors = list(detectors)
        self.config = config or DetectorConfig()
        self._generation = -1
        self._last_alert_s: dict[tuple[AlertType, int], float] = {}

    def evaluate(self, tick: Tick) -> list[Alert]:
        """Run every detector on tick; return the alerts past their cooldown."""
        if tick.generation != self._generation:
            self._reset(tick.generation)
        alerts = []
        for detector in self.detectors:
            for signal in detector.evaluate(tick):
                key = (detector.type, signal.team_id)
                last_s = self._last_alert_s.get(key)
                if last_s is not None and tick.play_s - last_s < self.config.cooldown_s:
                    continue
                self._last_alert_s[key] = tick.play_s
                alerts.append(_alert(detector.type, signal, tick.item.event))
        return alerts

    def _reset(self, generation: int) -> None:
        self._generation = generation
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
