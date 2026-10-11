"""Detectors: turn the rolling metrics into tactical alerts.

Detectors run once per tick of play time (`Detectors`), each keeping its own
state, and raise `Signal`s. `Detectors` rate-limits them per team and turns
them into `Alert`s, except during a replay or catch-up.
"""

from engine.detectors.baseline import Ewma
from engine.detectors.core import Detector, DetectorConfig, Detectors, Signal, Tick
from engine.detectors.momentum import Momentum, MomentumConfig

__all__ = [
    "Detector",
    "DetectorConfig",
    "Detectors",
    "Ewma",
    "Momentum",
    "MomentumConfig",
    "Signal",
    "Tick",
]
