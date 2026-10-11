"""Field tilt: who is playing in the opponent's third."""

from collections import Counter
from collections.abc import Iterable

from engine.metrics.pitch import in_attacking_third
from engine.schema.event_schema import EventOutcome, EventType, MatchEvent

TOUCH_TYPES = frozenset({EventType.pass_, EventType.carry, EventType.ball_receipt, EventType.shot})


def is_attacking_third_touch(e: MatchEvent) -> bool:
    """An on-ball action in the acting team's attacking third.

    A failed ball receipt means the ball never arrived, so it isn't a touch.
    Failed passes and missed shots still are.
    """
    if e.type not in TOUCH_TYPES or e.location is None:
        return False
    if e.type is EventType.ball_receipt and e.outcome is EventOutcome.failure:
        return False
    return in_attacking_third(e.location)


def field_tilt(events: Iterable[MatchEvent], team_ids: tuple[int, int]) -> dict[int, float]:
    """Each team's share (0-1) of the attacking-third touches in `events`.

    The two shares add up to 1. With no touches at all, both teams get 0.5:
    neither is tilting the pitch. Events by any other team id are ignored.
    """
    touches = Counter(e.team.id for e in events if is_attacking_third_touch(e))
    a, b = team_ids
    total = touches[a] + touches[b]
    if total == 0:
        return {a: 0.5, b: 0.5}
    return {a: touches[a] / total, b: touches[b] / total}
