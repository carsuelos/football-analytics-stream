"""Expected threat (xT): how much a pass or carry moved the ball towards a goal.

xT gives each cell of a 12x8 grid the probability that possession of the ball
there ends in a goal within the next few actions. A move from cell A to cell B
adds xT(B) - xT(A), which is negative for a move backwards.

The grid is Karun Singh's published one ("Introducing Expected Threat (xT)",
https://karun.in/blog/expected-threat.html). It has no licence, so
`make fetch-data` downloads it into data/xt/ instead of it being committed.
"""

import json
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from engine.metrics.actions import is_completed_move
from engine.metrics.pitch import GRID_COLS, GRID_ROWS, Point, grid_cell
from engine.schema.event_schema import MatchEvent

DEFAULT_GRID_PATH = Path(__file__).resolve().parents[4] / "data" / "xt" / "open_xt_12x8_v1.json"

MIN_VELOCITY_MINUTES = 1.0
"""Velocity divides by at least this many minutes, so one early pass can't spike it."""


class XTGridError(Exception):
    """The xT grid file is missing or malformed."""


@dataclass(frozen=True)
class XTGrid:
    """xT values as GRID_ROWS rows (across the pitch) of GRID_COLS values (along it)."""

    rows: tuple[tuple[float, ...], ...]

    def __post_init__(self) -> None:
        if len(self.rows) != GRID_ROWS or any(len(r) != GRID_COLS for r in self.rows):
            raise XTGridError(f"an xT grid needs {GRID_ROWS} rows of {GRID_COLS} values")
        if not all(math.isfinite(v) and v >= 0 for r in self.rows for v in r):
            raise XTGridError("xT values must be finite and non-negative")

    @classmethod
    def from_lists(cls, rows: Sequence[Sequence[float]]) -> "XTGrid":
        return cls(tuple(tuple(float(v) for v in r) for r in rows))

    @classmethod
    def load(cls, path: Path = DEFAULT_GRID_PATH) -> "XTGrid":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise XTGridError(f"no xT grid at {path}; run `make fetch-data`") from None
        except (OSError, ValueError) as e:
            raise XTGridError(f"cannot read the xT grid at {path}: {e}") from e
        try:
            return cls.from_lists(data)
        except (TypeError, ValueError, XTGridError) as e:
            raise XTGridError(f"malformed xT grid at {path}: {e}") from e

    def value(self, p: Point) -> float:
        col, row = grid_cell(p)
        return self.rows[row][col]


def xt_of_move(e: MatchEvent, grid: XTGrid) -> float | None:
    """xT added by a completed pass or carry; None for anything else."""
    if not is_completed_move(e):
        return None
    assert e.location is not None and e.end_location is not None
    return grid.value(e.end_location) - grid.value(e.location)


def xt_added(
    events: Iterable[MatchEvent], team_ids: tuple[int, int], grid: XTGrid
) -> dict[int, float]:
    """Each team's total xT added by its moves in `events`. Other team ids are ignored."""
    totals: defaultdict[int, float] = defaultdict(float)
    for e in events:
        xt = xt_of_move(e, grid)
        if xt is not None:
            totals[e.team.id] += xt
    return {t: totals[t] for t in team_ids}


def xt_velocity(xt: float, covered_s: float) -> float:
    """xT added per minute over a window that covers `covered_s` seconds of play.

    Early in a match a 5-minute window covers less than 5 minutes, so dividing
    by the full length would understate the rate. Dividing by very little would
    overstate it instead, hence the floor of MIN_VELOCITY_MINUTES.
    """
    return xt / max(covered_s / 60, MIN_VELOCITY_MINUTES)
