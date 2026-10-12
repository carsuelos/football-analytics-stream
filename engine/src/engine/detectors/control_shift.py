"""Control shift: the balance of pressure swinging from one team to the other."""

from dataclasses import dataclass

from engine.detectors.core import Signal
from engine.metrics import PressureComponents, pressure
from engine.schema.alert_schema import AlertType
from engine.ticks import Tick
from engine.windows import FIVE_MINUTES_S


@dataclass(frozen=True)
class ControlShiftConfig:
    window_s: float = FIVE_MINUTES_S
    """Compare the last window_s of play with the window_s before it."""
    smoothing: float = 5.0
    """Added to the total pressure when working out the balance, so a quiet
    spell (2 against 0, say) doesn't count as total control."""
    threshold: float = 0.5
    """The team's balance over the last window must reach this..."""
    previous_max: float = -0.2
    """...after being at most this over the window before."""


class ControlShift:
    """Signals when a team that was being pinned back is now on top.

    A team's pressure balance against the other is (a - b) / (a + b + smoothing):
    1 for total control, -1 for none. It signals when the balance swings from
    previous_max or below to threshold or above between two back-to-back
    windows, so it needs two full windows of play. Like goal threat, it keeps
    no state between ticks.
    """

    type = AlertType.control_shift

    def __init__(self, config: ControlShiftConfig | None = None) -> None:
        self.config = config or ControlShiftConfig()

    def reset(self) -> None:
        pass

    def evaluate(self, tick: Tick) -> list[Signal]:
        c = self.config
        if tick.windows.covered_s(2 * c.window_s) < 2 * c.window_s:
            return []
        last = tick.events(c.window_s)
        in_last = {e.id for e in last}
        previous = [e for e in tick.events(2 * c.window_s) if e.id not in in_last]
        now, before = pressure(last, tick.team_ids), pressure(previous, tick.team_ids)
        signals = []
        for team_id, other in (tick.team_ids, tick.team_ids[::-1]):
            balance = self._balance(now, team_id, other, tick)
            previous_balance = self._balance(before, team_id, other, tick)
            if balance >= c.threshold and previous_balance <= c.previous_max:
                name = tick.teams[team_id].name
                minutes = f"{c.window_s / 60:g}'"
                signals.append(
                    Signal(
                        team_id=team_id,
                        value=balance,
                        threshold=c.threshold,
                        window_s=c.window_s,
                        features={
                            "balance": balance,
                            "previous_balance": previous_balance,
                            "pressure_index": now[team_id].index(tick.metrics.weights),
                            "opponent_pressure_index": now[other].index(tick.metrics.weights),
                        },
                        message=(
                            f"{name} taking control: pressure balance {balance:+.2f}"
                            f" over the last {minutes}, from {previous_balance:+.2f}"
                            f" the {minutes} before"
                        ),
                    )
                )
        return signals

    def _balance(
        self, index: dict[int, PressureComponents], team_id: int, other: int, tick: Tick
    ) -> float:
        a = index[team_id].index(tick.metrics.weights)
        b = index[other].index(tick.metrics.weights)
        return (a - b) / (a + b + self.config.smoothing)
