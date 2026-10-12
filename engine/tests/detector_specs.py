"""Builders for detector tests: matches written as (clock, team, event fields)."""

from typing import Any

from engine.metrics import MetricsConfig, XTGrid
from engine.schema.common_schema import Team
from engine.schema.event_schema import EventType, MatchEvent, ShotDetail, ShotOutcome
from tests.factories import AWAY, event

Spec = tuple[float, Team, dict[str, Any]]

OWN_HALF = (40.0, 40.0)
ATT_HALF = (65.0, 40.0)  # attacking half, short of the final third
GRID = XTGrid.from_lists([[c / 100 for c in range(12)]] * 8)
"""xT is the column / 100: 0.00 in a team's own goal-line column to 0.11 at the other end."""
METRICS = MetricsConfig(GRID)


def build(*specs: Spec | list[Spec]) -> list[MatchEvent]:
    """First-half events from specs, in clock order with offsets 0, 1, 2..."""
    flat = [s for spec in specs for s in (spec if isinstance(spec, list) else [spec])]
    flat.sort(key=lambda s: s[0])
    return [event(1, clock, offset=i, team=team, **kw) for i, (clock, team, kw) in enumerate(flat)]


def touch(clock: float, team: Team = AWAY) -> Spec:
    """A pass in the team's own half that goes nowhere: no pressure, no xT."""
    return (clock, team, {"location": OWN_HALF})


def recoveries(team: Team, n: int, from_s: float) -> list[Spec]:
    """n attacking-half recoveries, one a second: 1 pressure point each."""
    return [
        (from_s + i, team, {"type": EventType.ball_recovery, "location": ATT_HALF})
        for i in range(n)
    ]


def progression(clock: float, team: Team, cols: int) -> Spec:
    """A completed pass along the touchline from the first grid column to column
    `cols`: adds cols / 100 xT and no pressure."""
    return (clock, team, {"location": (5.0, 5.0), "end_location": (cols * 10 + 5.0, 5.0)})


def shot(clock: float, team: Team, outcome: ShotOutcome, xg: float = 0.25) -> Spec:
    return (
        clock,
        team,
        {
            "type": EventType.shot,
            "location": (100.0, 40.0),
            "shot": ShotDetail(xg=xg, outcome=outcome),
        },
    )
