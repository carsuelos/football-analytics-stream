import pytest

from engine.metrics.pitch import (
    grid_cell,
    in_attacking_half,
    in_attacking_third,
    in_opponent_box,
)


@pytest.mark.parametrize(("x", "expected"), [(0, False), (59.9, False), (60, True), (120, True)])
def test_attacking_half_starts_at_halfway(x: float, expected: bool) -> None:
    assert in_attacking_half((x, 40)) is expected


@pytest.mark.parametrize(("x", "expected"), [(40, False), (79.9, False), (80, True), (120, True)])
def test_attacking_third_starts_at_x_80(x: float, expected: bool) -> None:
    assert in_attacking_third((x, 40)) is expected


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ((102, 18), True),  # corner of the box, on the lines
        ((120, 62), True),
        ((110, 40), True),
        ((101.9, 40), False),  # just outside the 18-yard line
        ((110, 17.9), False),  # wide of the box
        ((110, 62.1), False),
        ((18, 40), False),  # our own box
    ],
)
def test_opponent_box(point: tuple[float, float], expected: bool) -> None:
    assert in_opponent_box(point) is expected


@pytest.mark.parametrize(
    ("point", "cell"),
    [
        ((0, 0), (0, 0)),
        ((9.9, 9.9), (0, 0)),
        ((10, 10), (1, 1)),
        ((60, 40), (6, 4)),
        ((119.9, 79.9), (11, 7)),
        ((120, 80), (11, 7)),  # on the goal line / touchline
        ((-0.5, 80.5), (0, 7)),  # slightly off the pitch
        ((121, -1), (11, 0)),
        ((-15, -15), (0, 0)),  # far enough off for int() to go negative
    ],
)
def test_grid_cell(point: tuple[float, float], cell: tuple[int, int]) -> None:
    assert grid_cell(point) == cell
