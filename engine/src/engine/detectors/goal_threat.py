"""Goal threat: a team creating enough danger that a goal looks close."""

import math
from dataclasses import dataclass

from engine.detectors.core import Signal
from engine.metrics import pressure, xt_added, xt_velocity
from engine.schema.alert_schema import AlertType
from engine.schema.event_schema import EventType, MatchEvent, ShotOutcome
from engine.ticks import Tick
from engine.windows import FIVE_MINUTES_S


@dataclass(frozen=True)
class GoalThreatConfig:
    """A logistic score over two features, each divided by a scale.

    Fitted in Phase 3 (docs/MODEL.md, Step 5) so the score is the chance the
    team scores in the next 10' (about 7% on average). The scales are the
    features' standard deviations, so the weights compare: xT velocity
    carries about three times the weight of pressure.
    """

    window_s: float = FIVE_MINUTES_S
    bias: float = -2.03
    pressure_weight: float = 0.0412
    pressure_scale: float = 6.94
    """Pressure index."""
    xt_weight: float = 0.124
    xt_scale: float = 0.0196
    """xT added per minute."""
    threshold: float = 0.185
    """Tuned for about 2 alerts a match."""


class GoalThreat:
    """Signals when a team's recent pressure and progression add up to danger.

    Only play since the last goal in the window counts, by either team and
    including own goals: a goal is followed by a kick-off, and the danger that led to it is over.
    Shots need no feature of their own, since the pressure index already
    counts them, weighted by xG. The score has no memory, so this detector
    keeps no state.
    """

    type = AlertType.goal_threat

    def __init__(self, config: GoalThreatConfig | None = None) -> None:
        self.config = config or GoalThreatConfig()

    def reset(self) -> None:
        pass

    def evaluate(self, tick: Tick) -> list[Signal]:
        c = self.config
        events, covered_s = since_last_goal(tick, c.window_s)
        index = pressure(events, tick.team_ids)
        xt = xt_added(events, tick.team_ids, tick.metrics.grid)
        signals = []
        for team_id in tick.team_ids:
            press = index[team_id].index(tick.metrics.weights)
            velocity = xt_velocity(xt[team_id], covered_s)
            score = _sigmoid(
                c.bias
                + c.pressure_weight * press / c.pressure_scale
                + c.xt_weight * velocity / c.xt_scale
            )
            if score >= c.threshold:
                name = tick.teams[team_id].name
                signals.append(
                    Signal(
                        team_id=team_id,
                        value=score,
                        threshold=c.threshold,
                        window_s=c.window_s,
                        features={
                            "pressure_index": press,
                            "xt_velocity": velocity,
                            "covered_s": covered_s,
                        },
                        message=(
                            f"{name} goal threat {score:.0%}: pressure {press:.1f},"
                            f" xT {velocity:+.3f}/min over the last {_minutes(covered_s)}"
                        ),
                    )
                )
        return signals


def since_last_goal(tick: Tick, window_s: float) -> tuple[list[MatchEvent], float]:
    """The events of the last window_s of play after any goal in it, and how
    much play they cover."""
    items = tick.windows.events(window_s)
    goals = [i for i, item in enumerate(items) if _is_goal(item.event)]
    if not goals:
        return [i.event for i in items], tick.windows.covered_s(window_s)
    last_goal = goals[-1]
    return [i.event for i in items[last_goal + 1 :]], tick.play_s - items[last_goal].play_s


def _is_goal(e: MatchEvent) -> bool:
    if e.type is EventType.own_goal:
        return True
    return e.type is EventType.shot and e.shot is not None and e.shot.outcome is ShotOutcome.goal


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _minutes(seconds: float) -> str:
    return f"{seconds / 60:.1f}'".replace(".0'", "'")
