"""Builders for hand-made events and feed messages in tests."""

import itertools

from engine.clock import MatchClock, TimedEvent
from engine.schema.common_schema import Team
from engine.schema.event_schema import EventOutcome, EventType, MatchEvent
from engine.schema.feed_schema import FeedMarker, FeedMessage, FeedMessageKind

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
    match_id: int = 1,
    location: tuple[float, float] | None = None,
    end_location: tuple[float, float] | None = None,
    outcome: EventOutcome | None = None,
) -> MatchEvent:
    """An event at (period, clock_s). Ids are unique unless given."""
    n = next(_ids)
    return MatchEvent(
        schema_version=1,
        id=id or f"e{n}",
        match_id=match_id,
        offset=n if offset is None else offset,
        period=period,
        match_clock_s=clock_s,
        type=type,
        team=team,
        possession_id=1,
        possession_team_id=team.id,
        location=list(location) if location else None,
        end_location=list(end_location) if end_location else None,
        outcome=outcome,
    )


def times(events: list[MatchEvent]) -> list[tuple[int, float]]:
    """The (period, clock) of each event, for readable assertions."""
    return [(e.period, e.match_clock_s) for e in events]


def timed(events: list[MatchEvent]) -> list[TimedEvent]:
    """Place in-order events on the play-time axis with a fresh MatchClock."""
    clock = MatchClock()
    return [clock.advance(e) for e in events]


def feed_event(ev: MatchEvent) -> FeedMessage:
    return FeedMessage(schema_version=1, kind=FeedMessageKind.event, event=ev)


def feed_marker(
    kind: FeedMessageKind, offset: int, *, match_id: int = 1, period: int = 1, clock_s: float = 0
) -> FeedMessage:
    marker = FeedMarker(match_id=match_id, offset=offset, period=period, match_clock_s=clock_s)
    return FeedMessage(schema_version=1, kind=kind, marker=marker)
