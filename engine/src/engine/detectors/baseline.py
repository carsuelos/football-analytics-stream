"""What's normal for a series: an exponentially weighted mean and variance."""

import math


class Ewma:
    """Exponentially weighted mean and variance of a series sampled over play time.

    Each sample's weight halves every half_life_s seconds of play, so the
    baseline follows how a team is playing now rather than over the whole
    match. Weights decay with the time between samples, not their number, so
    a sample after a long gap counts for more, as it should.

    The update is the incremental form from Finch, "Incremental calculation of
    weighted mean and variance" (2009), with alpha worked out for each step.
    """

    def __init__(self, half_life_s: float) -> None:
        if half_life_s <= 0:
            raise ValueError(f"half_life_s must be positive, got {half_life_s}")
        self.half_life_s = half_life_s
        self.mean: float | None = None
        """None until the first sample."""
        self.variance = 0.0
        self._last_s = 0.0

    @property
    def std(self) -> float:
        return math.sqrt(self.variance)

    def add(self, x: float, at_s: float) -> None:
        """Add sample x taken at play time at_s."""
        if self.mean is None:
            self.mean = x
            self._last_s = at_s
            return
        if at_s < self._last_s:
            raise ValueError(f"sample at {at_s}s is before the latest one at {self._last_s}s")
        alpha = 1 - 0.5 ** ((at_s - self._last_s) / self.half_life_s)
        d = x - self.mean
        self.mean += alpha * d
        self.variance = (1 - alpha) * (self.variance + alpha * d * d)
        self._last_s = at_s
