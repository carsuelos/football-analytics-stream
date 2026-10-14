"""Control shift: the balance of pressure swinging from one team to the other."""

from dataclasses import dataclass

from engine.detectors.core import Signal
from engine.metrics import PressureComponents, pressure
from engine.schema.alert_schema import AlertType
from engine.schema.event_schema import MatchEvent
from engine.ticks import Tick
from engine.windows import FIVE_MINUTES_S


@dataclass(frozen=True)
class ControlShiftConfig:
    window_s: float = FIVE_MINUTES_S
    """Compare the last window_s of play with the window_s before it."""
    smoothing: float = 5.0
    """Added to the total pressure when working out the balance, so a quiet
    spell (2 against 0, say) doesn't count as total control."""
    threshold: float = 0.805
    """The team's balance over the last window must reach this..."""
    previous_max: float = 1.0
    """...after being at most this over the window before. Balances never
    exceed 1, so the default turns this condition off: Phase 3 tuning
    (docs/MODEL.md, Step 5) found that dominance predicts goals better than a
    swing does. Set it below 0 to signal only on swings."""


class ControlShift:
    """Signals when a team is on top, optionally only after being pinned back.

    A team's pressure balance against the other is (a - b) / (a + b + smoothing):
    1 for total control, -1 for none. It signals when the balance is at
    threshold or above over the last window after being at previous_max or
    below over the window before, so it needs two full windows of play. With
    the default previous_max the window before doesn't matter. Like goal
    threat, it keeps no state between ticks.
    """

    type = AlertType.control_shift

    def __init__(self, config: ControlShiftConfig | None = None) -> None:
        self.config = config or ControlShiftConfig()

    def reset(self) -> None:
        pass

    def evaluate(self, tick: Tick) -> list[Signal]:
        c = self.config
        halves = back_to_back(tick, c.window_s)
        if halves is None:
            return []
        last, previous = halves
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
                            f"{name} in control: pressure balance {balance:+.2f}"
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


def back_to_back(tick: Tick, window_s: float) -> tuple[list[MatchEvent], list[MatchEvent]] | None:
    """The events of the last window_s of play and of the window_s before it,
    or None until there have been two full windows of play."""
    if tick.windows.covered_s(2 * window_s) < 2 * window_s:
        return None
    last = tick.events(window_s)
    in_last = {e.id for e in last}
    return last, [e for e in tick.events(2 * window_s) if e.id not in in_last]
