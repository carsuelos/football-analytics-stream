"""What counts as which kind of action, shared by the metrics."""

from engine.schema.event_schema import EventOutcome, EventType, MatchEvent

ON_BALL_TYPES = frozenset(
    {EventType.pass_, EventType.carry, EventType.ball_receipt, EventType.shot, EventType.dribble}
)
MOVE_TYPES = frozenset({EventType.pass_, EventType.carry})


def is_on_ball(e: MatchEvent) -> bool:
    """The acting player had the ball: a failed receipt means it never arrived."""
    if e.type is EventType.ball_receipt and e.outcome is EventOutcome.failure:
        return False
    return e.type in ON_BALL_TYPES


def is_completed_move(e: MatchEvent) -> bool:
    """A pass or carry that kept the ball, with both ends known.

    Passes always carry an outcome. Carries have none, and count unless a
    failure is recorded.
    """
    return (
        e.type in MOVE_TYPES
        and e.outcome is not EventOutcome.failure
        and e.location is not None
        and e.end_location is not None
    )
