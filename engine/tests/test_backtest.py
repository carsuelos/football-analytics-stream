import json
from pathlib import Path

import pytest

from engine import backtest
from engine.backtest import Goal, feed_paths, read_feed, replay
from engine.detectors import Detectors
from engine.hub import MatchHub
from engine.pipeline import Pipeline
from engine.runner import run
from engine.schema.common_schema import DisallowedReason, Team
from engine.schema.event_schema import (
    DisallowedGoal,
    EventType,
    MatchEvent,
    ShotDetail,
    ShotOutcome,
)
from engine.schema.feed_schema import FeedMessage
from engine.schema.feed_schema import FeedMessageKind as K
from engine.ticks import Ticker
from engine.windows import InMemoryStateStore
from tests.factories import AWAY, HOME, event, feed_event, feed_marker
from tests.test_detectors import Fake
from tests.test_runner import METRICS, ListSource

FINAL = Path(__file__).resolve().parents[2] / "data" / "feeds" / "3869685.jsonl"


def shot(
    period: int, clock_s: float, offset: int, outcome: ShotOutcome, team: Team = HOME
) -> MatchEvent:
    return event(
        period,
        clock_s,
        offset=offset,
        type=EventType.shot,
        team=team,
        location=(110, 40),
        shot=ShotDetail(xg=0.3, outcome=outcome),
    )


def a_match() -> list[FeedMessage]:
    """Forty minutes of passes, with a goal each way, a saved shot, an own goal
    and a shootout."""
    events = [
        event(1, float(s), offset=i, team=(HOME, AWAY)[i % 2])
        for i, s in enumerate(range(0, 2400, 20))
    ]
    n = len(events)
    events += [
        shot(1, 2410, n, ShotOutcome.goal),
        shot(1, 2420, n + 1, ShotOutcome.saved, team=AWAY),
        event(1, 2430, offset=n + 2, type=EventType.own_goal, team=HOME),  # counts for AWAY
        shot(5, 0, n + 3, ShotOutcome.goal, team=AWAY),  # the shootout
    ]
    return [
        feed_marker(K.match_start, 0, head=0),
        *map(feed_event, events),
        feed_marker(K.match_end, len(events)),
    ]


def test_replay_finds_goals_and_the_end() -> None:
    r = replay(a_match(), METRICS)
    assert r.goals == [
        Goal(HOME.id, 2410, 120, own_goal=False),
        Goal(AWAY.id, 2430, 122, own_goal=True),
    ]
    assert (r.match_id, r.team_ids, r.end_play_s, r.ended) == (1, (HOME.id, AWAY.id), 2430, True)
    assert r.team_names == {HOME.id: HOME.name, AWAY.id: AWAY.name}
    assert (r.released, r.late_dropped, r.alerts, r.snapshots) == (124, 0, [], [])


def test_replay_drops_a_disallowed_goal() -> None:
    msgs = a_match()
    goal = next(m.event for m in msgs if m.event and m.event.offset == 120)
    var = event(1, 2440, offset=124, type=EventType.goal_disallowed, team=HOME).model_copy(
        update={"disallowed_goal": DisallowedGoal(event_id=goal.id, reason=DisallowedReason.foul)}
    )
    shootout = msgs[-2]
    r = replay([*msgs[:-2], feed_event(var), shootout, msgs[-1]], METRICS)
    assert [(g.team_id, g.own_goal) for g in r.goals] == [(AWAY.id, True)]


async def test_replay_matches_the_live_engine() -> None:
    """Offline replay raises exactly the alerts and snapshots run() gives the hub."""
    msgs = a_match()
    hub = MatchHub()
    await run(
        ListSource(*msgs),
        Pipeline(InMemoryStateStore()),
        ticker=Ticker(METRICS, tick_s=30),
        detectors=Detectors([Fake(fire=(HOME.id, AWAY.id))]),
        hub=hub,
        report=lambda _: None,
    )
    r = replay(
        msgs,
        METRICS,
        detectors=Detectors([Fake(fire=(HOME.id, AWAY.id))]),
        snapshots=True,
        tick_s=30,
    )
    assert hub.alerts and [a.alert for a in r.alerts] == hub.alerts
    assert r.snapshots == hub.snapshots
    assert [a.play_s for a in r.alerts][:2] == [40, 40]  # the first event past 00:30


def test_replay_calls_on_step_for_every_released_event() -> None:
    seen: list[tuple[int, bool]] = []
    replay(
        a_match(),
        METRICS,
        on_step=lambda _, s: seen.append((s.item.event.offset, s.tick is not None)),
        tick_s=30,
    )
    assert [o for o, _ in seen] == list(range(124))
    assert sum(t for _, t in seen) == 2430 // 30  # a tick every 30 s of play, from 00:30


def test_replay_needs_both_teams() -> None:
    with pytest.raises(ValueError, match="both teams"):
        replay([feed_marker(K.match_start, 0), feed_event(event(1, 0))], METRICS)


def test_read_feed_and_paths(tmp_path: Path) -> None:
    msgs = a_match()
    path = tmp_path / "1.jsonl"
    path.write_text("".join(m.model_dump_json(exclude_none=True) + "\n" for m in msgs) + "\n")
    (tmp_path / "matches.json").write_text("{}")
    assert list(read_feed(path)) == msgs
    assert feed_paths([tmp_path]) == [path]
    assert feed_paths([path, path]) == [path, path]


def test_cli_prints_a_line_per_match(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for id in (1, 2):
        (tmp_path / f"{id}.jsonl").write_text(
            "".join(m.model_dump_json() + "\n" for m in a_match())
        )
    grid = tmp_path / "grid.json"
    grid.write_text(json.dumps([[0.0] * 12] * 8))
    backtest.main([str(tmp_path), "--workers", "1", "--xt-grid", str(grid)])
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(lines) == 2
    assert lines[0]["score"] == [1, 1]
    assert lines[0]["teams"] == [HOME.name, AWAY.name]


@pytest.mark.skipif(not FINAL.exists(), reason="no exported feeds; run: make export")
def test_world_cup_final() -> None:
    (r,) = backtest.replay_files([FINAL])
    assert [g.team_id for g in r.goals].count(779) == 3  # Argentina 3-3 France
    assert len(r.goals) == 6
    assert r.ended and r.late_dropped == 2
