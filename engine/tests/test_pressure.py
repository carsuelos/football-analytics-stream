import pytest

from engine.metrics import PressureComponents, PressureWeights, pressure
from engine.schema.common_schema import Team
from engine.schema.event_schema import EventOutcome, EventType, MatchEvent, ShotDetail, ShotOutcome
from tests.factories import AWAY, HOME, event

IDS = (HOME.id, AWAY.id)

OWN_HALF = (40.0, 40.0)
ATT_HALF = (65.0, 40.0)  # attacking half, not the final third
FINAL_THIRD = (90.0, 10.0)  # final third, wide of the box
BOX = (110.0, 40.0)


def act(
    at: tuple[float, float] | None,
    *,
    type: EventType = EventType.pass_,
    team: Team = HOME,
    possession: int = 1,
    possession_team: Team | None = None,
    to: tuple[float, float] | None = None,
    outcome: EventOutcome | None = None,
    xg: float | None = None,
) -> MatchEvent:
    return event(
        1,
        0,
        type=type,
        team=team,
        location=at,
        end_location=to,
        outcome=outcome,
        possession_id=possession,
        possession_team=possession_team,
        shot=ShotDetail(xg=xg, outcome=ShotOutcome.saved) if xg is not None else None,
    )


def home(events: list[MatchEvent]) -> PressureComponents:
    return pressure(events, IDS)[HOME.id]


def test_nothing_happening_is_all_zero() -> None:
    assert pressure([], IDS) == {1: PressureComponents(), 2: PressureComponents()}
    assert PressureComponents().index(PressureWeights()) == 0


# --- recoveries ---


@pytest.mark.parametrize("type_", [EventType.ball_recovery, EventType.interception])
def test_recoveries_in_the_attacking_half_count(type_: EventType) -> None:
    assert home([act(ATT_HALF, type=type_), act((60, 0), type=type_)]).recoveries == 2


def test_recoveries_in_own_half_do_not() -> None:
    assert home([act(OWN_HALF, type=EventType.ball_recovery)]).recoveries == 0


def test_failed_recoveries_do_not_but_unknown_outcomes_do() -> None:
    failed = act(ATT_HALF, type=EventType.ball_recovery, outcome=EventOutcome.failure)
    unknown = act(ATT_HALF, type=EventType.interception, outcome=None)
    assert home([failed, unknown]).recoveries == 1


def test_recoveries_need_a_location_and_the_right_type() -> None:
    assert home([act(None, type=EventType.ball_recovery), act(ATT_HALF)]).recoveries == 0


# --- box entries ---


def test_completed_moves_into_the_box_are_entries() -> None:
    events = [
        act(FINAL_THIRD, to=BOX, outcome=EventOutcome.success),
        act(FINAL_THIRD, to=BOX, type=EventType.carry),
    ]
    assert home(events).box_entries == 2


def test_failed_moves_inside_moves_and_moves_out_are_not() -> None:
    events = [
        act(FINAL_THIRD, to=BOX, outcome=EventOutcome.failure),
        act(BOX, to=(115, 40), outcome=EventOutcome.success),
        act(BOX, to=FINAL_THIRD, outcome=EventOutcome.success),
        act(FINAL_THIRD, to=BOX, type=EventType.shot),
    ]
    assert home(events).box_entries == 0


# --- shots ---


def test_each_shot_is_worth_one_plus_its_xg() -> None:
    events = [act(BOX, type=EventType.shot, xg=0.5), act(BOX, type=EventType.shot, xg=0.05)]
    assert home(events).shot_value == pytest.approx(2.55)


def test_a_shot_without_detail_is_worth_one() -> None:
    assert home([act(None, type=EventType.shot)]).shot_value == 1.0


# --- sustained final-third actions ---


def test_runs_shorter_than_three_count_nothing() -> None:
    assert home([act(FINAL_THIRD), act(FINAL_THIRD)]).sustained_actions == 0


def test_a_run_of_three_counts_all_three_and_grows_by_one() -> None:
    assert home([act(FINAL_THIRD)] * 3).sustained_actions == 3
    assert home([act(FINAL_THIRD)] * 5).sustained_actions == 5


def test_an_action_outside_the_final_third_breaks_the_run() -> None:
    events = [act(FINAL_THIRD)] * 2 + [act(ATT_HALF)] + [act(FINAL_THIRD)] * 2
    assert home(events).sustained_actions == 0


def test_a_new_possession_breaks_the_run() -> None:
    events = [act(FINAL_THIRD)] * 2 + [act(FINAL_THIRD, possession=2)] * 2
    assert home(events).sustained_actions == 0


def test_two_separate_runs_add_up() -> None:
    events = [act(FINAL_THIRD)] * 3 + [act(FINAL_THIRD, possession=2)] * 4
    assert home(events).sustained_actions == 7


@pytest.mark.parametrize(
    "type_",
    [EventType.pass_, EventType.carry, EventType.ball_receipt, EventType.shot, EventType.dribble],
)
def test_on_ball_types_extend_a_run(type_: EventType) -> None:
    assert home([act(FINAL_THIRD)] * 2 + [act(FINAL_THIRD, type=type_)]).sustained_actions == 3


def test_off_ball_and_opponent_events_neither_extend_nor_break_a_run() -> None:
    events = [
        act(FINAL_THIRD),
        act(FINAL_THIRD, type=EventType.pressure, team=AWAY, possession_team=HOME),
        act(FINAL_THIRD, type=EventType.foul_won),
        act(FINAL_THIRD),
        act(FINAL_THIRD, type=EventType.ball_receipt, outcome=EventOutcome.failure),
        act(None),
        act(FINAL_THIRD),
    ]
    assert home(events).sustained_actions == 3


def test_on_ball_actions_without_possession_do_not_count() -> None:
    # e.g. a defender's touch while the other team is in possession
    events = [act(FINAL_THIRD, possession_team=AWAY)] * 3
    assert home(events).sustained_actions == 0


# --- box actions ---


def test_box_actions_count_from_the_second_in_a_possession() -> None:
    assert home([act(BOX)]).box_actions == 0
    assert home([act(BOX)] * 3).box_actions == 2


def test_box_actions_are_counted_per_possession() -> None:
    events = [act(BOX)] * 2 + [act(BOX, possession=2)] + [act(BOX, possession=3)] * 3
    assert home(events).box_actions == 1 + 0 + 2


def test_leaving_the_box_does_not_restart_the_count() -> None:
    assert home([act(BOX), act(FINAL_THIRD), act(BOX)]).box_actions == 1


def test_box_actions_need_possession_and_the_ball() -> None:
    events = [
        act(BOX),
        act(BOX, possession_team=AWAY),
        act(BOX, type=EventType.pressure),
        act(BOX, type=EventType.ball_receipt, outcome=EventOutcome.failure),
    ]
    assert home(events).box_actions == 0


# --- teams and the index ---


def test_components_are_per_team_and_other_teams_are_ignored() -> None:
    stranger = Team(id=99, name="Stranger")
    events = [
        act(BOX, type=EventType.shot, team=AWAY, xg=0.25),
        act(BOX, type=EventType.shot, team=stranger),
        act(ATT_HALF, type=EventType.ball_recovery),
    ]
    result = pressure(events, (AWAY.id, HOME.id))
    assert list(result) == [2, 1]
    assert result[2] == PressureComponents(shot_value=1.25)
    assert result[1] == PressureComponents(recoveries=1)


def test_index_is_the_weighted_sum() -> None:
    c = PressureComponents(
        recoveries=2, box_entries=3, shot_value=1.5, sustained_actions=8, box_actions=4
    )
    assert c.index(PressureWeights()) == pytest.approx(
        2 * 1.0 + 3 * 1.5 + 1.5 * 2.0 + 8 * 0.25 + 4 * 0.5
    )
    custom = PressureWeights(
        recoveries=10, box_entries=0, shot_value=0, sustained_actions=0, box_actions=1
    )
    assert c.index(custom) == 24


def test_negative_weights_are_rejected() -> None:
    with pytest.raises(ValueError, match="shot_value"):
        PressureWeights(shot_value=-1)
    PressureWeights(shot_value=0)
