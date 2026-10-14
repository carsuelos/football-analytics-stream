import json
from pathlib import Path

import numpy as np
from engine.features import FEATURE_NAMES
from engine.schema.common_schema import Team
from engine.schema.event_schema import EventOutcome, EventType, MatchEvent, ShotDetail, ShotOutcome
from engine.schema.feed_schema import FeedMarker, FeedMessage, FeedMessageKind

from model.dataset import Dataset, labels, match_rows

HOME, AWAY = Team(id=1, name="Home"), Team(id=2, name="Away")


def ev(n: int, clock_s: float, team: Team, **kw: object) -> MatchEvent:
    return MatchEvent.model_validate(
        {
            "schema_version": 1,
            "id": f"e{n}",
            "match_id": 7,
            "offset": n,
            "period": 1,
            "match_clock_s": clock_s,
            "type": EventType.pass_,
            "team": team,
            "possession_id": n,
            "possession_team_id": team.id,
            "location": [60, 40],
            "end_location": [70, 40],
            "outcome": EventOutcome.success,
            **kw,
        }
    )


def write_feed(path: Path, events: list[MatchEvent]) -> None:
    def marker(kind: FeedMessageKind, offset: int) -> FeedMessage:
        m = FeedMarker(match_id=7, offset=offset, period=1, match_clock_s=0, head=0)
        return FeedMessage(schema_version=1, kind=kind, marker=m)

    messages = [
        marker(FeedMessageKind.match_start, 0),
        *(FeedMessage(schema_version=1, kind=FeedMessageKind.event, event=e) for e in events),
        marker(FeedMessageKind.match_end, len(events)),
    ]
    path.write_text("".join(m.model_dump_json(exclude_none=True) + "\n" for m in messages))


def test_labels_look_only_ahead() -> None:
    play_s = np.array([900.0, 900.0, 1200.0, 1500.0, 1560.0])
    team = np.array([1, 2, 1, 1, 1])
    y = labels(play_s, team, [(1, 1500.0)])
    # 900 -> 1500 is 10' exactly: in (t, t + 10']; 1200 -> 1500 is 5'; at 1500 the goal is now.
    assert y.tolist() == [
        [False, True],
        [False, False],
        [True, True],
        [False, False],
        [False, False],
    ]


def test_match_rows(tmp_path: Path) -> None:
    events = [ev(i, s, (HOME, AWAY)[i % 2]) for i, s in enumerate(range(0, 2400, 10))]
    goal = ev(
        len(events),
        1500.5,
        AWAY,
        type=EventType.shot,
        location=[110, 40],
        end_location=None,
        outcome=None,
        shot=ShotDetail(xg=0.4, outcome=ShotOutcome.goal),
    )
    events.append(goal)
    events.sort(key=lambda e: e.match_clock_s)
    feed, grid = tmp_path / "7.jsonl", tmp_path / "grid.json"
    write_feed(feed, events)
    grid.write_text(json.dumps([[0.01 * c for c in range(12)]] * 8))

    d = match_rows(feed, grid)
    assert d.x.shape == (len(d), len(FEATURE_NAMES))
    # Ticks every 30s from 15' to the last event at 39:50, for each team.
    assert len(d) == 2 * len(range(900, 2400, 30))
    assert set(d.match_id) == {7}
    assert d.play_s.min() == 900
    away = d.team_id == AWAY.id
    assert d.label(10)[away & (d.play_s >= 900.5) & (d.play_s < 1500.5)].all()
    assert not d.label(10)[~away].any()
    assert not d.label(5)[away & (d.play_s < 1200.5)].any()
    after = away & (d.play_s > 1500.5)
    assert (d.column("score_diff")[after] == 1).all()
    # The tick at 1500 comes out of the reorder buffer together with the goal
    # half a second later, and must not see it.
    assert (d.column("score_diff")[away & (d.play_s <= 1500)] == 0).all()
    assert (d.column("since_goal_min") >= 0).all()


def test_save_and_load(tmp_path: Path) -> None:
    n = 3
    d = Dataset(
        np.arange(n * len(FEATURE_NAMES), dtype=float).reshape(n, -1),
        np.array([[True, False]] * n),
        np.array([1, 1, 2]),
        np.array([5, 6, 5]),
        np.array([900.0, 900.0, 930.0]),
    )
    d.save(tmp_path / "d.npz", xt_grid="g.json")
    back = Dataset.load(tmp_path / "d.npz")
    assert np.array_equal(back.x, d.x) and np.array_equal(back.y, d.y)
    assert back.names == FEATURE_NAMES
    assert back.meta == {"xt_grid": "g.json"}
    both = Dataset.concat([d, back])
    assert len(both) == 2 * n
