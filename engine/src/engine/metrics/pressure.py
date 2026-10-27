"""Sustained pressure index: how hard a team is pinning the other back.

The index is a weighted sum of five components, computed per team over the
events in a window:

- recoveries: ball recoveries and interceptions won in the attacking half
- box entries: completed passes and carries from outside the opponent box into it
- shot value: 1 + xG for each shot, so a big chance outweighs a speculative one
- sustained actions: on-ball actions in the final third that are part of an
  unbroken run of at least SUSTAINED_RUN in one possession
- box actions: on-ball actions in the opponent box within one possession,
  from the second onwards, so a single touch that is lost counts nothing

Runs and possessions are only seen inside the window: one that started before
it counts from the window's first event.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, fields

from engine.metrics.actions import is_completed_move, is_on_ball
from engine.metrics.pitch import in_attacking_half, in_attacking_third, in_opponent_box
from engine.schema.event_schema import EventOutcome, EventType, MatchEvent

RECOVERY_TYPES = frozenset({EventType.ball_recovery, EventType.interception})
SUSTAINED_RUN = 3


@dataclass(frozen=True)
class PressureWeights:
    """Weight of each component in the index.

    The defaults were a first guess. Phase 3 (docs/MODEL.md, Step 5) fitted
    them to goals in the next 10' and kept them: the fit was no better on the
    World Cup (AUC 0.557 against 0.560).
    """

    recoveries: float = 1.0
    box_entries: float = 1.5
    shot_value: float = 2.0
    sustained_actions: float = 0.25
    box_actions: float = 0.5

    def __post_init__(self) -> None:
        negative = [f.name for f in fields(self) if getattr(self, f.name) < 0]
        if negative:
            raise ValueError(f"pressure weights must not be negative: {', '.join(negative)}")


@dataclass(frozen=True)
class PressureComponents:
    """One team's raw component values; kept so alerts can say what drove the index."""

    recoveries: int = 0
    box_entries: int = 0
    shot_value: float = 0.0
    sustained_actions: int = 0
    box_actions: int = 0

    def index(self, weights: PressureWeights) -> float:
        return (
            weights.recoveries * self.recoveries
            + weights.box_entries * self.box_entries
            + weights.shot_value * self.shot_value
            + weights.sustained_actions * self.sustained_actions
            + weights.box_actions * self.box_actions
        )


def pressure(
    events: Sequence[MatchEvent], team_ids: tuple[int, int]
) -> dict[int, PressureComponents]:
    """Each team's pressure components over `events`, which must be in match order."""
    return {
        team: PressureComponents(
            recoveries=_recoveries(events, team),
            box_entries=_box_entries(events, team),
            shot_value=_shot_value(events, team),
            sustained_actions=_sustained_actions(events, team),
            box_actions=_box_actions(events, team),
        )
        for team in team_ids
    }


def _recoveries(events: Sequence[MatchEvent], team: int) -> int:
    return sum(
        1
        for e in events
        if e.team.id == team
        and e.type in RECOVERY_TYPES
        and e.outcome is not EventOutcome.failure
        and e.location is not None
        and in_attacking_half(e.location)
    )


def _box_entries(events: Sequence[MatchEvent], team: int) -> int:
    return sum(
        1
        for e in events
        if e.team.id == team
        and is_completed_move(e)
        and e.location is not None
        and e.end_location is not None
        and not in_opponent_box(e.location)
        and in_opponent_box(e.end_location)
    )


def _shot_value(events: Sequence[MatchEvent], team: int) -> float:
    return sum(
        1 + ((e.shot.xg or 0.0) if e.shot else 0.0)
        for e in events
        if e.team.id == team and e.type is EventType.shot
    )


def _own_on_ball(events: Sequence[MatchEvent], team: int) -> list[MatchEvent]:
    """The team's on-ball actions while it has possession, where it happened is known."""
    return [
        e
        for e in events
        if e.team.id == team
        and e.possession_team_id == team
        and e.location is not None
        and is_on_ball(e)
    ]


def _sustained_actions(events: Sequence[MatchEvent], team: int) -> int:
    total = run = 0
    possession: int | None = None
    for e in _own_on_ball(events, team):
        assert e.location is not None
        if e.possession_id != possession:
            possession, run = e.possession_id, 0
        if not in_attacking_third(e.location):
            run = 0
            continue
        run += 1
        if run == SUSTAINED_RUN:
            total += SUSTAINED_RUN
        elif run > SUSTAINED_RUN:
            total += 1
    return total


def _box_actions(events: Sequence[MatchEvent], team: int) -> int:
    per_possession = Counter(
        e.possession_id
        for e in _own_on_ball(events, team)
        if e.location is not None and in_opponent_box(e.location)
    )
    return sum(n - 1 for n in per_possession.values())
