from collections.abc import Iterable
from pathlib import Path

import pytest

from engine.backtest import read_feed, steps
from engine.incidents import IncidentTracker
from engine.metrics import MetricsConfig, XTGrid
from engine.pipeline import Pipeline
from engine.schema.common_schema import DisallowedReason, Player, Team, TeamScore
from engine.schema.event_schema import (
    Card,
    DisallowedGoal,
    EventType,
    MatchEvent,
    ShotDetail,
    ShotOutcome,
    ShotType,
)
from engine.schema.feed_schema import FeedMessage
from engine.schema.feed_schema import FeedMessageKind as K
from engine.schema.incident_schema import Incident, IncidentKind
from engine.ticks import Ticker
from engine.windows import InMemoryStateStore
from tests.factories import AWAY, HOME, event, feed_event, feed_marker

METRICS = MetricsConfig(XTGrid.from_lists([[0.0] * 12] * 8))
FINAL = Path(__file__).resolve().parents[2] / "data" / "feeds" / "3869685.jsonl"
MESSI = Player(id=10, name="Messi")


def shot(
    clock_s: float,
    outcome: ShotOutcome,
    team: Team = HOME,
    *,
    period: int = 1,
    type: ShotType | None = None,
    id: str | None = None,
) -> MatchEvent:
    e = event(period, clock_s, id=id, type=EventType.shot, team=team)
    return e.model_copy(
        update={"shot": ShotDetail(xg=0.3, outcome=outcome, type=type), "player": MESSI}
    )


def with_(e: MatchEvent, **update: object) -> MatchEvent:
    return e.model_copy(update=update)


def incidents(
    events: list[MatchEvent], tracker: IncidentTracker | None = None
) -> tuple[list[Incident], list[TeamScore] | None]:
    """Every incident in a match of events, kicking off with a pass each way,
    and the score at the end."""
    events = [event(1, 0, team=HOME), event(1, 1, team=AWAY), *events]
    for i, e in enumerate(events):
        events[i] = e.model_copy(update={"offset": i})
    msgs: list[FeedMessage] = [
        feed_marker(K.match_start, 0, head=0),
        *map(feed_event, events),
        feed_marker(K.match_end, len(events)),
    ]
    return run(msgs, tracker or IncidentTracker())


def run(
    msgs: Iterable[FeedMessage], tracker: IncidentTracker, pipeline: Pipeline | None = None
) -> tuple[list[Incident], list[TeamScore] | None]:
    pipeline = pipeline or Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    found = [
        i for s in steps(msgs, pipeline, Ticker(METRICS)) for i in tracker.observe(pipeline, s.item)
    ]
    return found, tracker.score(pipeline)


def goals(score: list[TeamScore] | None) -> list[tuple[int, int | None]]:
    assert score is not None
    return [(s.goals, s.shootout) for s in score]


def test_goals_and_the_score() -> None:
    found, score = incidents(
        [
            shot(60, ShotOutcome.goal),
            shot(120, ShotOutcome.saved, AWAY),
            event(1, 180, type=EventType.own_goal, team=HOME),  # counts for AWAY
        ]
    )
    assert [(i.kind, i.team_id, goals(i.score)) for i in found] == [
        (IncidentKind.goal, HOME.id, [(1, None), (0, None)]),
        (IncidentKind.own_goal, AWAY.id, [(1, None), (1, None)]),
    ]
    assert goals(score) == [(1, None), (1, None)]
    assert found[0].player == MESSI
    assert (found[0].period, found[0].match_clock_s, found[0].play_s) == (1, 60, 60)


def test_penalties() -> None:
    foul = with_(event(1, 50, type=EventType.foul_committed, team=AWAY), penalty_awarded=True)
    won = with_(event(1, 50, type=EventType.foul_won, team=HOME), penalty_awarded=True)
    handball = with_(
        event(1, 200, type=EventType.foul_committed, team=HOME, id="hb"),
        penalty_awarded=True,
        card=Card.yellow,
        player=MESSI,
    )
    found, score = incidents(
        [
            foul,
            won,  # the same penalty, flagged twice
            shot(60, ShotOutcome.goal, type=ShotType.penalty),
            handball,  # only the foul is flagged
            shot(210, ShotOutcome.saved, AWAY, type=ShotType.penalty),
        ]
    )
    assert [(i.kind, i.team_id) for i in found] == [
        (IncidentKind.penalty_awarded, HOME.id),
        (IncidentKind.penalty_goal, HOME.id),
        (IncidentKind.penalty_awarded, AWAY.id),
        (IncidentKind.yellow_card, HOME.id),
        (IncidentKind.penalty_missed, AWAY.id),
    ]
    assert found[2].player == MESSI  # who gave it away
    assert found[0].id != found[2].id
    assert goals(score) == [(1, None), (0, None)]


def test_a_second_penalty_to_the_same_team_counts_once_taken() -> None:
    award = [
        with_(event(1, s, type=EventType.foul_won, team=HOME), penalty_awarded=True)
        for s in (50, 300)
    ]
    found, _ = incidents([award[0], shot(60, ShotOutcome.post, type=ShotType.penalty), award[1]])
    assert [i.kind for i in found] == [
        IncidentKind.penalty_awarded,
        IncidentKind.penalty_missed,
        IncidentKind.penalty_awarded,
    ]


def test_cards() -> None:
    found, _ = incidents(
        [
            with_(event(1, 10, type=EventType.foul_committed, team=AWAY), card=Card.yellow),
            with_(event(1, 20, type=EventType.other, team=AWAY), card=Card.second_yellow),
            with_(event(1, 30, type=EventType.foul_committed, team=HOME), card=Card.red),
        ]
    )
    assert [(i.kind, i.team_id) for i in found] == [
        (IncidentKind.yellow_card, AWAY.id),
        (IncidentKind.second_yellow, AWAY.id),
        (IncidentKind.red_card, HOME.id),
    ]


def test_a_disallowed_goal_comes_off_the_score() -> None:
    var = event(1, 100, type=EventType.goal_disallowed, team=HOME)
    found, score = incidents(
        [
            shot(60, ShotOutcome.goal, id="g1"),
            shot(90, ShotOutcome.goal, id="g2"),
            with_(
                var, disallowed_goal=DisallowedGoal(event_id="g1", reason=DisallowedReason.offside)
            ),
            # Cancelling it again, or something that was never a goal, does nothing.
            with_(
                var,
                id="again",
                disallowed_goal=DisallowedGoal(event_id="g1", reason=DisallowedReason.other),
            ),
            with_(
                var,
                id="nope",
                disallowed_goal=DisallowedGoal(event_id="xx", reason=DisallowedReason.other),
            ),
        ]
    )
    assert [(i.kind, goals(i.score)) for i in found] == [
        (IncidentKind.goal, [(1, None), (0, None)]),
        (IncidentKind.goal, [(2, None), (0, None)]),
        (IncidentKind.goal_disallowed, [(1, None), (0, None)]),
    ]
    cancelled = found[2]
    assert (cancelled.cancels, cancelled.reason, cancelled.team_id) == (
        found[0].id,
        DisallowedReason.offside,
        HOME.id,
    )
    assert cancelled.player == MESSI  # the scorer, from the goal
    assert goals(score) == [(1, None), (0, None)]


def test_the_shootout_has_its_own_count() -> None:
    found, score = incidents(
        [
            shot(60, ShotOutcome.goal),
            shot(7200, ShotOutcome.goal, AWAY, period=5, type=ShotType.penalty),
            shot(7260, ShotOutcome.saved, HOME, period=5, type=ShotType.penalty),
        ]
    )
    assert [(i.kind, goals(i.score)) for i in found] == [
        (IncidentKind.goal, [(1, None), (0, None)]),
        (IncidentKind.shootout_goal, [(1, 0), (0, 1)]),
        (IncidentKind.shootout_miss, [(1, 0), (0, 1)]),
    ]
    assert goals(score) == [(1, 0), (0, 1)]


def test_no_score_before_both_teams_appear() -> None:
    tracker = IncidentTracker()
    pipeline = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    msgs = [feed_marker(K.match_start, 0, head=0), feed_event(shot(60, ShotOutcome.goal))]
    found, score = run(msgs, tracker, pipeline)
    assert (found, score) == ([], None)


def test_it_starts_over_with_the_pipeline() -> None:
    tracker = IncidentTracker()
    pipeline = Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    events = [event(1, 0, team=HOME), event(1, 1, team=AWAY), shot(60, ShotOutcome.goal)]
    msgs = [
        feed_marker(K.match_start, 0, head=0),
        *(feed_event(e.model_copy(update={"offset": i})) for i, e in enumerate(events)),
    ]
    first, score = run(msgs, tracker, pipeline)
    assert goals(score) == [(1, None), (0, None)]
    # The DVR seeking back to the start: a new generation, the same incidents.
    again, score = run(msgs, tracker, pipeline)
    assert again == first
    assert goals(score) == [(1, None), (0, None)]
    # Seeking back once more: no score until both teams are back, then 0-0.
    run([feed_marker(K.match_start, 0, head=0)], tracker, pipeline)
    assert tracker.score(pipeline) is None
    _, score = run(
        [feed_event(e.model_copy(update={"offset": i})) for i, e in enumerate(events[:2])],
        tracker,
        pipeline,
    )
    assert goals(score) == [(0, None), (0, None)]


@pytest.mark.skipif(not FINAL.exists(), reason="run make export to replay the final")
def test_the_world_cup_final() -> None:
    tracker = IncidentTracker()
    found, score = run(read_feed(FINAL), tracker)
    kinds = [i.kind for i in found]
    assert kinds.count(IncidentKind.goal) == 3
    assert kinds.count(IncidentKind.penalty_goal) == 3
    assert kinds.count(IncidentKind.penalty_awarded) == 3
    assert kinds.count(IncidentKind.yellow_card) == 8
    assert (kinds.count(IncidentKind.shootout_goal), kinds.count(IncidentKind.shootout_miss)) == (
        6,
        2,
    )
    assert goals(score) == [(3, 4), (3, 2)]  # Argentina, France
    di_maria = next(i for i in found if i.kind is IncidentKind.goal)
    assert (di_maria.period, int(di_maria.match_clock_s)) == (1, 2122)  # 35:22
