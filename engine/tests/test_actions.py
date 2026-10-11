import pytest

from engine.metrics.actions import is_completed_move, is_on_ball
from engine.schema.event_schema import EventOutcome, EventType
from tests.factories import event


@pytest.mark.parametrize(
    "type_",
    [EventType.pass_, EventType.carry, EventType.ball_receipt, EventType.shot, EventType.dribble],
)
def test_on_ball_types(type_: EventType) -> None:
    assert is_on_ball(event(1, 0, type=type_))
    assert is_on_ball(event(1, 0, type=type_, outcome=EventOutcome.success))


@pytest.mark.parametrize(
    "type_", [EventType.pressure, EventType.ball_recovery, EventType.duel, EventType.clearance]
)
def test_off_ball_types(type_: EventType) -> None:
    assert not is_on_ball(event(1, 0, type=type_))


def test_only_a_failed_receipt_loses_the_ball() -> None:
    assert not is_on_ball(event(1, 0, type=EventType.ball_receipt, outcome=EventOutcome.failure))
    assert is_on_ball(event(1, 0, type=EventType.pass_, outcome=EventOutcome.failure))
    assert is_on_ball(event(1, 0, type=EventType.dribble, outcome=EventOutcome.failure))


def test_completed_moves() -> None:
    a, b = (10.0, 10.0), (20.0, 20.0)
    ok = EventOutcome.success
    assert is_completed_move(event(1, 0, location=a, end_location=b, outcome=ok))
    assert is_completed_move(event(1, 0, type=EventType.carry, location=a, end_location=b))
    failed = event(1, 0, location=a, end_location=b, outcome=EventOutcome.failure)
    assert not is_completed_move(failed)
    assert not is_completed_move(event(1, 0, location=a, outcome=ok))
    assert not is_completed_move(event(1, 0, end_location=b, outcome=ok))
    assert not is_completed_move(event(1, 0, type=EventType.shot, location=a, end_location=b))
