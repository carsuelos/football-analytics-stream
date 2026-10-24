"""The full-time model: the chance of another goal before full time.

A prediction market's "over" contract pays on one more goal, by a team or by
anyone, before the end of regulation (90 minutes plus stoppage). This model
prices it, from the same features as the goal model plus the minutes left:
trained offline (`make fulltime`, model/src/model/fulltime.py) and shipped as
JSON next to this module, two logistic regressions with hinges on the minutes
left, run here with no machine-learning library. See docs/MODEL.md, step 7.

How long is left isn't known until the referee blows: stoppage time varies by
match, and grew from 2022 (matches run to about 100 minutes of play where they
used to end at about 95). So the model takes the expected minutes left given
how long the competition's matches usually last (`end_min`) and how much they
vary around that (`end_residuals`).
"""

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.features import FEATURE_NAMES

DEFAULT_FULLTIME_PATH = Path(__file__).with_name("fulltime_model.json")


class FullTimeModelError(Exception):
    """The model file is missing, malformed or doesn't match the engine's features."""


def minutes_left(minute: float, end_min: float, residuals: Sequence[float]) -> float:
    """The expected minutes of regulation left at `minute` of play, for matches
    that end at end_min + r, r drawn from residuals, given the match is still on."""
    ends = [end_min + r - minute for r in residuals if end_min + r > minute]
    return math.fsum(ends) / len(ends) if ends else MIN_LEFT


MIN_LEFT = 0.5
"""Minutes left past every end the residuals allow: the match is still on, so not none."""


def terms(x: Sequence[float], left: float, knots: Sequence[float]) -> list[float]:
    """A row's inputs: the features, the minutes left, and max(0, left - knot) per knot."""
    return [*x, left, *(max(0.0, left - k) for k in knots)]


@dataclass(frozen=True)
class Part:
    """One standardized logistic regression over `terms`."""

    mean: tuple[float, ...]
    scale: tuple[float, ...]
    coef: tuple[float, ...]
    intercept: float
    base_rate: float

    def probability(self, values: Sequence[float]) -> float:
        z = self.intercept + math.fsum(
            c * (v - m) / s
            for v, m, s, c in zip(values, self.mean, self.scale, self.coef, strict=True)
        )
        return 1 / (1 + math.exp(-z))


@dataclass(frozen=True)
class FullTime:
    """A team's chances at a tick."""

    team: float
    """The team scores again before full time."""
    game: float
    """Anyone scores again before full time."""


@dataclass(frozen=True)
class FullTimeModel:
    features: tuple[str, ...]
    left_knots: tuple[float, ...]
    end_min: float
    """How many minutes of play the matches it prices usually last, stoppage time included."""
    end_residuals: tuple[float, ...]
    """How a match's end varies around end_min (quantiles, in minutes)."""
    team: Part
    game: Part
    warmup_s: float
    xt_grid_sha256: str
    info: dict[str, Any]

    def __post_init__(self) -> None:
        if self.features != FEATURE_NAMES:
            raise FullTimeModelError(
                "the full-time model was trained on different features than the engine computes;"
                " rebuild the dataset and retrain (make dataset fulltime)"
            )
        n = len(self.features) + 1 + len(self.left_knots)
        for part in (self.team, self.game):
            if not len(part.mean) == len(part.scale) == len(part.coef) == n:
                raise FullTimeModelError(f"expected {n} means, scales and coefficients")
            if any(s <= 0 for s in part.scale):
                raise FullTimeModelError("scales must be positive")

    @classmethod
    def from_json(cls, doc: Mapping[str, Any]) -> "FullTimeModel":
        data = dict(doc)

        def part(d: Mapping[str, Any]) -> Part:
            return Part(
                mean=tuple(float(v) for v in d["mean"]),
                scale=tuple(float(v) for v in d["scale"]),
                coef=tuple(float(v) for v in d["coef"]),
                intercept=float(d["intercept"]),
                base_rate=float(d["base_rate"]),
            )

        return cls(
            features=tuple(str(f) for f in data.pop("features")),
            left_knots=tuple(float(k) for k in data.pop("left_knots")),
            end_min=float(data.pop("end_min")),
            end_residuals=tuple(float(r) for r in data.pop("end_residuals")),
            team=part(data.pop("team")),
            game=part(data.pop("game")),
            warmup_s=float(data.pop("warmup_s")),
            xt_grid_sha256=str(data.pop("xt_grid_sha256")),
            info=data,
        )

    @classmethod
    def load(cls, path: Path = DEFAULT_FULLTIME_PATH) -> "FullTimeModel":
        try:
            return cls.from_json(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            raise FullTimeModelError(f"no full-time model at {path}") from None
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            raise FullTimeModelError(f"cannot read the full-time model at {path}: {e!r}") from e

    def part(self, target: str) -> Part:
        return {"team": self.team, "game": self.game}[target]

    def values(self, x: Sequence[float]) -> list[float]:
        """A row's inputs, from its features (in FEATURE_NAMES order)."""
        left = minutes_left(x[_MINUTE], self.end_min, self.end_residuals)
        return terms(x, left, self.left_knots)

    def predict(self, features: Mapping[int, Sequence[float]]) -> dict[int, FullTime]:
        """Each team's chances, from both teams' features at one tick. The game's
        chance is the mean of the two teams' views, so it's the same for both."""
        rows = {team: self.values(x) for team, x in features.items()}
        game = [self.game.probability(v) for v in rows.values()]
        g = math.fsum(game) / len(game)
        return {team: FullTime(self.team.probability(v), g) for team, v in rows.items()}


_MINUTE = FEATURE_NAMES.index("minute")
