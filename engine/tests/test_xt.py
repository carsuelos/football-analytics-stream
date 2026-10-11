import json
from pathlib import Path

import pytest

from engine.metrics import XTGrid, XTGridError, xt_added, xt_velocity
from engine.metrics.xt import xt_of_move
from engine.schema.common_schema import Team
from engine.schema.event_schema import EventOutcome, EventType, MatchEvent
from tests.factories import AWAY, HOME, event

IDS = (HOME.id, AWAY.id)

# A made-up grid that is easy to read: column c, row r is worth c + r / 100.
# Each cell is 10 yards along the pitch and 10 wide.
ROWS = [[c + r / 100 for c in range(12)] for r in range(8)]
GRID = XTGrid.from_lists(ROWS)


def move(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    team: Team = HOME,
    type: EventType = EventType.pass_,
    outcome: EventOutcome | None = EventOutcome.success,
) -> MatchEvent:
    return event(1, 0, team=team, type=type, location=start, end_location=end, outcome=outcome)


def test_value_looks_up_row_then_column() -> None:
    assert GRID.value((5, 5)) == 0.0
    assert GRID.value((115, 5)) == 11.0
    assert GRID.value((5, 75)) == 0.07
    assert GRID.value((65, 35)) == 6.03


def test_a_forward_pass_adds_the_difference() -> None:
    assert xt_of_move(move((15, 5), (45, 5)), GRID) == 3.0


def test_a_backward_pass_subtracts() -> None:
    assert xt_of_move(move((45, 5), (15, 5)), GRID) == -3.0


def test_a_pass_within_one_cell_adds_nothing() -> None:
    assert xt_of_move(move((11, 11), (19, 19)), GRID) == 0.0


def test_successful_carry_with_no_outcome_counts() -> None:
    assert xt_of_move(move((15, 5), (25, 5), type=EventType.carry, outcome=None), GRID) == 1.0


@pytest.mark.parametrize("type_", [EventType.pass_, EventType.carry])
def test_failed_moves_add_nothing(type_: EventType) -> None:
    assert (
        xt_of_move(move((15, 5), (45, 5), type=type_, outcome=EventOutcome.failure), GRID) is None
    )


@pytest.mark.parametrize(
    "type_", [EventType.shot, EventType.dribble, EventType.ball_receipt, EventType.clearance]
)
def test_only_passes_and_carries_are_moves(type_: EventType) -> None:
    assert xt_of_move(move((15, 5), (45, 5), type=type_), GRID) is None


def test_moves_without_both_locations_are_skipped() -> None:
    no_end = event(1, 0, location=(15, 5), outcome=EventOutcome.success)
    no_start = event(1, 0, end_location=(15, 5), outcome=EventOutcome.success)
    assert xt_of_move(no_end, GRID) is None
    assert xt_of_move(no_start, GRID) is None


def test_xt_added_sums_per_team() -> None:
    events = [
        move((15, 5), (45, 5)),  # home +3
        move((45, 5), (35, 5)),  # home -1
        move((15, 5), (25, 5), team=AWAY),  # away +1
        move((15, 5), (95, 5), outcome=EventOutcome.failure),  # ignored
        move((15, 5), (95, 5), team=Team(id=99, name="Stranger")),  # ignored
    ]
    assert xt_added(events, IDS, GRID) == {1: 2.0, 2: 1.0}


def test_xt_added_is_zero_for_a_team_without_moves() -> None:
    assert xt_added([move((15, 5), (25, 5))], IDS, GRID) == {1: 1.0, 2: 0.0}
    assert list(xt_added([], (AWAY.id, HOME.id), GRID)) == [2, 1]


@pytest.mark.parametrize(
    ("xt", "covered_s", "expected"),
    [
        (1.5, 300, 0.3),  # a full 5-minute window
        (1.5, 150, 0.6),  # only 2.5 minutes of play so far
        (1.5, 60, 1.5),  # exactly the floor
        (1.5, 20, 1.5),  # under the floor: divided by 1 minute, not 1/3
        (1.5, 0, 1.5),
        (-0.6, 120, -0.3),
    ],
)
def test_velocity(xt: float, covered_s: float, expected: float) -> None:
    assert xt_velocity(xt, covered_s) == pytest.approx(expected)


@pytest.mark.parametrize(
    "rows",
    [
        ROWS[:7],
        [*ROWS[:7], ROWS[7][:11]],
        [*ROWS[:7], [*ROWS[7][:11], -0.1]],
        [*ROWS[:7], [*ROWS[7][:11], float("nan")]],
        [*ROWS[:7], [*ROWS[7][:11], float("inf")]],
    ],
    ids=["7 rows", "11 columns", "negative", "nan", "inf"],
)
def test_grid_shape_and_values_are_checked(rows: list[list[float]]) -> None:
    with pytest.raises(XTGridError):
        XTGrid.from_lists(rows)


def test_load_reads_rows_of_columns(tmp_path: Path) -> None:
    path = tmp_path / "xt.json"
    path.write_text(json.dumps(ROWS))
    assert XTGrid.load(path) == GRID


def test_load_explains_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(XTGridError, match="make fetch-data"):
        XTGrid.load(tmp_path / "missing.json")


@pytest.mark.parametrize("content", ["not json", '{"a": 1}', "[[1, 2]]", '[["x"]]', "3"], ids=repr)
def test_load_rejects_malformed_files(tmp_path: Path, content: str) -> None:
    path = tmp_path / "xt.json"
    path.write_text(content)
    with pytest.raises(XTGridError, match=str(path)):
        XTGrid.load(path)
