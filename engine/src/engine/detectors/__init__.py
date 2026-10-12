"""Detectors: turn the rolling metrics into tactical alerts.

Detectors run on each tick of play time (see `engine.ticks`), each keeping its
own state, and raise `Signal`s. `Detectors` rate-limits them per team and
turns them into `Alert`s.

- `Momentum`: a team pressing much harder than its own recent normal.
- `GoalThreat`: pressure and progression adding up to a likely goal.
- `ControlShift`: the balance of pressure swinging to the team that was pinned back.
"""

from engine.detectors.baseline import Ewma
from engine.detectors.control_shift import ControlShift, ControlShiftConfig
from engine.detectors.core import Detector, DetectorConfig, Detectors, Signal
from engine.detectors.goal_threat import GoalThreat, GoalThreatConfig
from engine.detectors.momentum import Momentum, MomentumConfig

__all__ = [
    "ControlShift",
    "ControlShiftConfig",
    "Detector",
    "DetectorConfig",
    "Detectors",
    "Ewma",
    "GoalThreat",
    "GoalThreatConfig",
    "Momentum",
    "MomentumConfig",
    "Signal",
]
