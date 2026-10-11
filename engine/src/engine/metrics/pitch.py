"""Pitch geometry on StatsBomb's 120x80 coordinates.

The simulator orients every event so the acting team attacks towards x = 120,
so "attacking third" or "opponent box" never depends on which team acted or
which half it is.
"""

from collections.abc import Sequence

PITCH_LENGTH = 120.0
PITCH_WIDTH = 80.0

HALFWAY_X = PITCH_LENGTH / 2
ATTACKING_THIRD_X = PITCH_LENGTH * 2 / 3

# The penalty area: 18 yards deep, 44 yards wide, centred on the goal.
BOX_X = 102.0
BOX_Y_MIN = 18.0
BOX_Y_MAX = 62.0

# The expected-threat grid: 12 columns along the pitch, 8 rows across it.
GRID_COLS = 12
GRID_ROWS = 8

Point = Sequence[float]


def in_attacking_half(p: Point) -> bool:
    return p[0] >= HALFWAY_X


def in_attacking_third(p: Point) -> bool:
    return p[0] >= ATTACKING_THIRD_X


def in_opponent_box(p: Point) -> bool:
    x, y = p
    return x >= BOX_X and BOX_Y_MIN <= y <= BOX_Y_MAX


def grid_cell(p: Point) -> tuple[int, int]:
    """The (column, row) of the xT grid cell containing p.

    Points on the far touchline or goal line belong to the last cell, and
    points slightly off the pitch (StatsBomb has a few) to the nearest one.
    """
    x, y = p
    col = int(x / PITCH_LENGTH * GRID_COLS)
    row = int(y / PITCH_WIDTH * GRID_ROWS)
    return _clamp(col, GRID_COLS), _clamp(row, GRID_ROWS)


def _clamp(i: int, n: int) -> int:
    return min(max(i, 0), n - 1)
