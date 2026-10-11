"""Momentum shift: a team pressing much harder than it has been."""

from dataclasses import dataclass

from engine.detectors.baseline import Ewma
from engine.detectors.core import Signal, Tick
from engine.metrics import pressure
from engine.schema.alert_schema import AlertType
from engine.windows import FIVE_MINUTES_S


@dataclass(frozen=True)
class MomentumConfig:
    window_s: float = FIVE_MINUTES_S
    """The pressure index is measured over this window."""
    half_life_s: float = 600.0
    """How quickly the baseline forgets: older play counts half as much per half-life."""
    warmup_s: float = 900.0
    """No signals in the first warmup_s of play, while the baselines settle."""
    std_floor: float = 3.0
    """Lowest spread used for z, so a quiet spell doesn't turn small rises into alerts."""
    threshold: float = 2.0
    """Signal when z reaches this."""


class Momentum:
    """Signals when a team's pressure index is well above its own recent normal.

    Each team is compared only with itself: z is how many standard deviations
    its pressure over the last window is above its EWMA baseline. The baseline
    gets the new sample after z is worked out, so a surge isn't measured
    against a baseline it has already pulled up.
    """

    type = AlertType.momentum_shift

    def __init__(self, config: MomentumConfig | None = None) -> None:
        self.config = config or MomentumConfig()
        self._baselines: dict[int, Ewma] = {}

    def reset(self) -> None:
        self._baselines = {}

    def evaluate(self, tick: Tick) -> list[Signal]:
        c = self.config
        index = pressure(tick.events(c.window_s), tick.team_ids)
        signals = []
        for team_id in tick.team_ids:
            x = index[team_id].index(tick.metrics.weights)
            baseline = self._baselines.setdefault(team_id, Ewma(c.half_life_s))
            if baseline.mean is not None and tick.play_s >= c.warmup_s:
                z = (x - baseline.mean) / max(baseline.std, c.std_floor)
                if z >= c.threshold:
                    name = tick.teams[team_id].name
                    signals.append(
                        Signal(
                            team_id=team_id,
                            value=z,
                            threshold=c.threshold,
                            window_s=c.window_s,
                            features={
                                "pressure_index": x,
                                "baseline_mean": baseline.mean,
                                "baseline_std": baseline.std,
                            },
                            message=(
                                f"{name} momentum: pressure {x:.1f} over the last"
                                f" {c.window_s / 60:g}', against a usual {baseline.mean:.1f}"
                                f" (z {z:+.1f})"
                            ),
                        )
                    )
            baseline.add(x, tick.play_s)
        return signals
