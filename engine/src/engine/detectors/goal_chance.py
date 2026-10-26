"""Goal chance: the trained model's probability that a team scores soon.

The model is trained offline (model/, `make train` and `make export-model`) on
the features in `engine.features`, and shipped as a small JSON file next to
this module: a logistic regression with hinges on the minute, so running it is
a dot product, with no machine-learning library at run time. See docs/MODEL.md.
"""

import argparse
import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.detectors.core import Signal
from engine.detectors.fulltime import FullTimeModel
from engine.features import FEATURE_NAMES, FeatureTracker
from engine.schema.alert_schema import AlertType
from engine.ticks import Tick

DEFAULT_MODEL_PATH = Path(__file__).with_name("goal_model.json")
DRIVERS = 3
"""How many of the play features pushing the probability up most an alert reports."""
AFTER_GOAL_MIN = 1.0
"""No alerts this soon after a goal (by either team): the goal itself pushes
the features up (the shot, its xG, the score), so an alert then reacts to the
goal rather than predicting one. If the chance stays high it comes after."""


class GoalModelError(Exception):
    """The model file is missing, malformed or doesn't match the engine's features."""


@dataclass(frozen=True)
class GoalModel:
    """A standardized logistic regression over FEATURE_NAMES, plus
    max(0, minute - knot) for each knot:

        p = sigmoid(intercept + sum(coef * (term - mean) / scale))
    """

    features: tuple[str, ...]
    minute_knots: tuple[float, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    coef: tuple[float, ...]
    intercept: float
    horizon_min: int
    threshold: float
    """Alert at or above this probability."""
    base_rate: float
    """How often a team scores within the horizon in the training data."""
    warmup_s: float
    """No predictions before this much play: the model never saw those ticks."""
    xt_grid_sha256: str
    """The xT grid the features were computed with (sha256, first 12 hex digits)."""
    info: dict[str, Any]
    """Everything else in the file (how it was trained, its scores)."""

    def __post_init__(self) -> None:
        if self.features != FEATURE_NAMES:
            raise GoalModelError(
                "the model was trained on different features than the engine computes;"
                " rebuild the dataset and retrain (make dataset train export-model)"
            )
        n = len(self.features) + len(self.minute_knots)
        if not len(self.mean) == len(self.scale) == len(self.coef) == n:
            raise GoalModelError(f"expected {n} means, scales and coefficients")
        if any(s <= 0 for s in self.scale):
            raise GoalModelError("scales must be positive")

    @classmethod
    def load(cls, path: Path = DEFAULT_MODEL_PATH) -> "GoalModel":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                features=tuple(str(f) for f in data.pop("features")),
                minute_knots=tuple(float(k) for k in data.pop("minute_knots")),
                mean=tuple(float(v) for v in data.pop("mean")),
                scale=tuple(float(v) for v in data.pop("scale")),
                coef=tuple(float(v) for v in data.pop("coef")),
                intercept=float(data.pop("intercept")),
                horizon_min=int(data.pop("horizon_min")),
                threshold=float(data.pop("threshold")),
                base_rate=float(data.pop("base_rate")),
                warmup_s=float(data.pop("warmup_s")),
                xt_grid_sha256=str(data.pop("xt_grid_sha256")),
                info=data,
            )
        except FileNotFoundError:
            raise GoalModelError(f"no goal model at {path}") from None
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            raise GoalModelError(f"cannot read the goal model at {path}: {e!r}") from e

    @property
    def terms(self) -> tuple[str, ...]:
        return (*self.features, *(f"minute>{k:g}" for k in self.minute_knots))

    def contributions(self, x: Sequence[float]) -> list[float]:
        """Each term's push on the log-odds, in `terms` order."""
        minute = x[self.features.index("minute")]
        values = [*x, *(max(0.0, minute - k) for k in self.minute_knots)]
        return [
            c * (v - m) / s
            for v, m, s, c in zip(values, self.mean, self.scale, self.coef, strict=True)
        ]

    def probability(self, x: Sequence[float]) -> float:
        """The probability of scoring within the horizon, given features in FEATURE_NAMES order."""
        return _sigmoid(self.intercept + math.fsum(self.contributions(x)))


def grid_digest(path: Path) -> str:
    """The digest GoalModel.xt_grid_sha256 is compared with."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def grid_mismatch(model: GoalModel, grid_path: Path) -> str | None:
    """A warning if the engine's xT grid isn't the one the model was trained with."""
    try:
        digest = grid_digest(grid_path)
    except OSError:
        return None
    if digest == model.xt_grid_sha256:
        return None
    return (
        f"the goal model was trained with a different xT grid ({model.xt_grid_sha256})"
        f" than {grid_path.name} ({digest}); its probabilities will be off"
    )


def add_goal_model_args(parser: argparse.ArgumentParser) -> None:
    """--goal-model PATH and --no-goal-model, setting args.goal_model (a Path or None)."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--goal-model",
        type=Path,
        metavar="PATH",
        help="the goal model for goal_chance alerts (default: the one shipped with the engine)",
    )
    group.add_argument(
        "--no-goal-model",
        dest="goal_model",
        action="store_const",
        const=None,
        help="no goal_chance alerts",
    )
    parser.set_defaults(goal_model=DEFAULT_MODEL_PATH)


class GoalChance:
    """Signals when the goal model gives a team a high chance of scoring soon.

    It computes the model's features at every tick, from the start of the
    match (they include running totals), but predicts only after the model's
    warm-up. Alerts report the probability, the base rate and the play
    features (not the clock or the score) pushing the probability up most,
    each "high" or "low" against its training mean. With a full-time model,
    they also report what a prediction market's next "over" lines are worth:
    the chance that the team scores again before full time (`ft_team`, for
    its line `team_line`, e.g. 2.5 at 2 goals) and that anyone does
    (`ft_game`, for the match's `game_line`).
    """

    type = AlertType.goal_chance

    def __init__(
        self,
        model: GoalModel,
        threshold: float | None = None,
        fulltime: FullTimeModel | None = None,
    ) -> None:
        self.model = model
        self.threshold = model.threshold if threshold is None else threshold
        self.fulltime = fulltime
        self.tracker = FeatureTracker()

    def reset(self) -> None:
        self.tracker.reset()

    def evaluate(self, tick: Tick) -> list[Signal]:
        m = self.model
        features = self.tracker.observe(tick)
        if tick.play_s < m.warmup_s:
            return []
        signals = []
        ft = self.fulltime.predict(features) if self.fulltime and len(features) == 2 else {}
        for team_id, x in features.items():
            values = dict(zip(m.features, x, strict=True))
            if (
                values["goals_for"] + values["goals_against"] > 0
                and values["since_goal_min"] < AFTER_GOAL_MIN
            ):
                continue
            push = m.contributions(x)
            p = _sigmoid(m.intercept + math.fsum(push))
            if p < self.threshold:
                continue
            means = dict(zip(m.features, m.mean, strict=False))
            drivers = sorted(
                (c, name)
                for c, name in zip(push, m.terms, strict=True)
                if c > 0 and name in values and name not in _GAME_STATE
            )[::-1][:DRIVERS]
            team = tick.teams[team_id].name
            why = ", ".join(
                f"{'high' if values[n] > means[n] else 'low'} {describe(n)}" for _, n in drivers
            )
            reported = {"base_rate": m.base_rate, **{n: values[n] for _, n in drivers}}
            message = (
                f"{team}: {p:.0%} chance to score in the next {m.horizon_min}'"
                f" (usually {m.base_rate:.0%})" + (f": {why}" if why else "")
            )
            if team_id in ft:
                team_line = values["goals_for"] + 0.5
                game_line = values["goals_for"] + values["goals_against"] + 0.5
                reported |= {
                    "ft_team": ft[team_id].team,
                    "team_line": team_line,
                    "ft_game": ft[team_id].game,
                    "game_line": game_line,
                }
                message += (
                    f". By full time: {ft[team_id].team:.0%} to score again"
                    f" ({team} over {team_line:g}), {ft[team_id].game:.0%} for any goal"
                    f" (over {game_line:g})"
                )
            signals.append(
                Signal(
                    team_id=team_id,
                    value=p,
                    threshold=self.threshold,
                    window_s=m.horizon_min * 60.0,
                    features=reported,
                    message=message,
                )
            )
        return signals


_STATS = {
    "tilt": "field tilt",
    "xt": "xT",
    "pressure": "pressure",
    "shots": "shots",
    "xg": "xG",
    "box_entries": "box entries",
    "box_actions": "box actions",
    "recoveries": "recoveries",
}
_GAME_STATE = {
    "minute": "the minute",
    "extra_time": "extra time",
    "score_diff": "the score",
    "goals_for": "goals scored",
    "goals_against": "goals conceded",
    "since_goal_min": "time since the last goal",
}


def describe(feature: str) -> str:
    """A feature's name in words: xt_10 is "xT (last 10')", opp_shots_match
    is "opponent's shots (match)"."""
    if feature in _GAME_STATE:
        return _GAME_STATE[feature]
    owner = "opponent's " if feature.startswith("opp_") else ""
    stat, _, span = feature.removeprefix("opp_").rpartition("_")
    when = "match" if span == "match" else f"last {span}'"
    return f"{owner}{_STATS.get(stat, stat)} ({when})"


def _sigmoid(x: float) -> float:
    if x < 0:
        e = math.exp(x)
        return e / (1 + e)
    return 1 / (1 + math.exp(-x))
