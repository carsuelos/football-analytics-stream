"""Match metrics, computed on demand from the events in a window.

Every metric is a pure function of a list of events, so a window can be
recomputed from scratch at any time: nothing to undo when events slide out,
and nothing to rebuild after a seek.
"""

from engine.metrics.field_tilt import field_tilt

__all__ = ["field_tilt"]
