"""Builders for hand-made events and feed messages in tests."""

import itertools

from engine.clock import MatchClock, TimedEvent
from engine.metrics import MetricsConfig
from engine.pipeline import Pipeline
from engine.schema.alert_schema import Alert, AlertType
from engine.schema.common_schema import Player, Team, TeamScore
from engine.schema.event_schema import EventOutcome, EventType, MatchEvent, ShotDetail
from engine.schema.feed_schema import FeedMarker, FeedMessage, FeedMessageKind
from engine.schema.incident_schema import Incident, IncidentKind
from engine.ticks import Tick
from engine.windows import InMemoryStateStore

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
    possession_id: int = 1,
    possession_team: Team | None = None,
    shot: ShotDetail | None = None,
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
        possession_id=possession_id,
        possession_team_id=(possession_team or team).id,
        location=list(location) if location else None,
        end_location=list(end_location) if end_location else None,
        outcome=outcome,
        shot=shot,
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
    kind: FeedMessageKind,
    offset: int,
    *,
    match_id: int = 1,
    period: int = 1,
    clock_s: float = 0,
    head: int | None = None,
) -> FeedMessage:
    marker = FeedMarker(
        match_id=match_id, offset=offset, period=period, match_clock_s=clock_s, head=head
    )
    return FeedMessage(schema_version=1, kind=kind, marker=marker)


def tick_after(events: list[MatchEvent], metrics: MetricsConfig) -> Tick:
    """The Tick a detector would see on the last of `events`, which must be in
    order and include both teams."""
    p = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    items = [
        i
        for msg in [feed_marker(FeedMessageKind.match_start, 0), *map(feed_event, events)]
        for i in p.handle(msg)
    ]
    assert p.windows is not None and p.team_ids is not None
    return Tick(items[-1], p.windows, p.team_ids, p.teams, metrics)


def alert(n: int = 0) -> Alert:
    return Alert(
        schema_version=1,
        id=f"1-control_shift-2-{n}",
        match_id=1,
        offset=n,
        period=2,
        match_clock_s=4947.0,
        type=AlertType.control_shift,
        team_id=2,
        value=0.6,
        threshold=0.5,
        window_s=300,
        features={"balance": 0.6},
        message="France taking control",
    )


def incident(n: int = 0) -> Incident:
    return Incident(
        schema_version=1,
        id=f"1-goal-{n}-goal",
        match_id=1,
        offset=n,
        period=1,
        match_clock_s=2122.0,
        play_s=2122.0,
        kind=IncidentKind.goal,
        team_id=1,
        player=Player(id=7, name="Ángel Di María"),
        score=[TeamScore(team_id=1, goals=2), TeamScore(team_id=2, goals=0)],
    )
