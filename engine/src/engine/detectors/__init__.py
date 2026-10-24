"""Detectors: turn the rolling metrics into tactical alerts.

Detectors run on each tick of play time (see `engine.ticks`), each keeping its
own state, and raise `Signal`s. `Detectors` rate-limits them per team and
turns them into `Alert`s.

- `Momentum`: a team pressing much harder than its own recent normal.
- `GoalThreat`: pressure and progression adding up to a likely goal.
- `ControlShift`: the balance of pressure swinging to the team that was pinned back.
- `GoalChance`: the trained goal model's probability of scoring in the next 10'.
"""

from engine.detectors.baseline import Ewma
from engine.detectors.control_shift import ControlShift, ControlShiftConfig
from engine.detectors.core import Detector, DetectorConfig, Detectors, Signal
from engine.detectors.fulltime import (
    DEFAULT_FULLTIME_PATH,
    FullTime,
    FullTimeModel,
    FullTimeModelError,
)
from engine.detectors.goal_chance import DEFAULT_MODEL_PATH, GoalChance, GoalModel, GoalModelError
from engine.detectors.goal_threat import GoalThreat, GoalThreatConfig
from engine.detectors.momentum import Momentum, MomentumConfig

__all__ = [
    "DEFAULT_FULLTIME_PATH",
    "DEFAULT_MODEL_PATH",
    "ControlShift",
    "ControlShiftConfig",
    "Detector",
    "DetectorConfig",
    "Detectors",
    "Ewma",
    "FullTime",
    "FullTimeModel",
    "FullTimeModelError",
    "GoalChance",
    "GoalModel",
    "GoalModelError",
    "GoalThreat",
    "GoalThreatConfig",
    "Momentum",
    "MomentumConfig",
    "Signal",
    "default_detectors",
]


def default_detectors(
    goal_model: GoalModel | None = None, fulltime: FullTimeModel | None = None
) -> Detectors:
    """The live engine's detectors: the rules, and goal chance if given a model
    (with the shipped full-time model unless another is given)."""
    rules: list[Detector] = [Momentum(), GoalThreat(), ControlShift()]
    if not goal_model:
        return Detectors(rules)
    return Detectors([*rules, GoalChance(goal_model, fulltime=fulltime or _shipped_fulltime())])


def _shipped_fulltime() -> FullTimeModel | None:
    try:
        return FullTimeModel.load(DEFAULT_FULLTIME_PATH)
    except FullTimeModelError:
        return None
