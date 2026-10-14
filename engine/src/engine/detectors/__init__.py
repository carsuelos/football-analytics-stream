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
from engine.detectors.goal_chance import DEFAULT_MODEL_PATH, GoalChance, GoalModel, GoalModelError
from engine.detectors.goal_threat import GoalThreat, GoalThreatConfig
from engine.detectors.momentum import Momentum, MomentumConfig

__all__ = [
    "DEFAULT_MODEL_PATH",
    "ControlShift",
    "ControlShiftConfig",
    "Detector",
    "DetectorConfig",
    "Detectors",
    "Ewma",
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


def default_detectors(goal_model: GoalModel | None = None) -> Detectors:
    """The live engine's detectors: the rules, and goal chance if given a model."""
    rules: list[Detector] = [Momentum(), GoalThreat(), ControlShift()]
    return Detectors(rules + ([GoalChance(goal_model)] if goal_model else []))
