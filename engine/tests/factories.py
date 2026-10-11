"""Builders for hand-made events in tests."""

import itertools

from engine.clock import MatchClock, TimedEvent
from engine.schema.common_schema import Team
from engine.schema.event_schema import EventType, MatchEvent

HOME = Team(id=1, name="Home FC")
AWAY = Team(id=2, name="Away FC")

_ids = itertools.count()


def event(
    period: int,
    clock_s: float,
    *,
    offset: int | None = None,
    id: str | None = None,
    type: EventType = EventType.pass_,
    team: Team = HOME,
) -> MatchEvent:
    """An event at (period, clock_s). Ids are unique unless given."""
    n = next(_ids)
    return MatchEvent(
        schema_version=1,
        id=id or f"e{n}",
        match_id=1,
        offset=n if offset is None else offset,
        period=period,
        match_clock_s=clock_s,
        type=type,
        team=team,
        possession_id=1,
        possession_team_id=team.id,
    )


def times(events: list[MatchEvent]) -> list[tuple[int, float]]:
    """The (period, clock) of each event, for readable assertions."""
    return [(e.period, e.match_clock_s) for e in events]


def timed(events: list[MatchEvent]) -> list[TimedEvent]:
    """Place in-order events on the play-time axis with a fresh MatchClock."""
    clock = MatchClock()
    return [clock.advance(e) for e in events]
