import pytest

from engine.metrics import field_tilt
from engine.schema.common_schema import Team
from engine.schema.event_schema import EventOutcome, EventType, MatchEvent
from tests.factories import AWAY, HOME, event

IDS = (HOME.id, AWAY.id)
DEEP = (100.0, 40.0)  # in the acting team's attacking third
MIDFIELD = (60.0, 40.0)


def touch(
    team: Team = HOME,
    at: tuple[float, float] = DEEP,
    type: EventType = EventType.pass_,
    outcome: EventOutcome | None = None,
) -> MatchEvent:
    return event(1, 0, team=team, location=at, type=type, outcome=outcome)


def test_neutral_when_nobody_reaches_the_final_third() -> None:
    assert field_tilt([], IDS) == {1: 0.5, 2: 0.5}
    assert field_tilt([touch(at=MIDFIELD), touch(AWAY, at=MIDFIELD)], IDS) == {1: 0.5, 2: 0.5}


def test_shares_of_attacking_third_touches() -> None:
    events = [touch(), touch(), touch(), touch(AWAY), touch(at=MIDFIELD)]
    assert field_tilt(events, IDS) == {1: 0.75, 2: 0.25}


def test_one_sided() -> None:
    assert field_tilt([touch(AWAY)], IDS) == {1: 0.0, 2: 1.0}


def test_keys_follow_the_given_team_order() -> None:
    assert list(field_tilt([touch()], (AWAY.id, HOME.id))) == [2, 1]


@pytest.mark.parametrize(
    "type_", [EventType.pass_, EventType.carry, EventType.ball_receipt, EventType.shot]
)
def test_touch_types_count(type_: EventType) -> None:
    assert field_tilt([touch(type=type_)], IDS)[1] == 1.0


@pytest.mark.parametrize(
    "type_", [EventType.pressure, EventType.duel, EventType.clearance, EventType.ball_recovery]
)
def test_other_types_do_not(type_: EventType) -> None:
    assert field_tilt([touch(type=type_)], IDS)[1] == 0.5


def test_failed_receipt_is_not_a_touch_but_failed_pass_is() -> None:
    failed_receipt = touch(type=EventType.ball_receipt, outcome=EventOutcome.failure)
    assert field_tilt([failed_receipt], IDS)[1] == 0.5
    failed_pass = touch(type=EventType.pass_, outcome=EventOutcome.failure)
    assert field_tilt([failed_pass], IDS)[1] == 1.0


def test_events_without_location_are_skipped() -> None:
    assert field_tilt([event(1, 0)], IDS) == {1: 0.5, 2: 0.5}


def test_other_team_ids_are_ignored() -> None:
    stranger = Team(id=99, name="Stranger")
    assert field_tilt([touch(stranger), touch(AWAY)], IDS) == {1: 0.0, 2: 1.0}
