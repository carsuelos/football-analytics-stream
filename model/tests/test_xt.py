import json
from pathlib import Path

import numpy as np
import pytest
from engine.metrics.pitch import GRID_COLS

from model.xt import Counts, count_file, is_penalty, score_grid, solve, zone

A, B = zone((5, 5)), zone((115, 40))  # far from goal; right in front of it


def ev(type: str, loc: tuple[float, float], **kw: object) -> dict[str, object]:
    return {"type": type, "location": list(loc), "period": 1, **kw}


def test_zones() -> None:
    assert zone((0, 0)) == 0
    assert zone((119.9, 0)) == GRID_COLS - 1
    assert zone((0, 79.9)) == 7 * GRID_COLS
    assert zone((120, 80)) == 8 * GRID_COLS - 1  # the far corner is the last cell


def test_a_zone_that_always_shoots_is_worth_its_conversion_rate() -> None:
    c = Counts.zero()
    c.shots[B], c.goals[B] = 10, 3
    assert solve(c).xt.reshape(-1)[B] == pytest.approx(0.3)


def test_value_flows_back_along_moves_that_keep_the_ball() -> None:
    c = Counts.zero()
    c.shots[B], c.goals[B] = 4, 2  # B: shoots, scores half the time
    c.moves[A], c.transitions[A, B] = 4, 3  # A: moves, a quarter of them lost
    xt = solve(c).xt.reshape(-1)
    assert xt[A] == pytest.approx(0.75 * 0.5)


def test_moves_within_a_zone_do_not_change_its_value() -> None:
    c = Counts.zero()
    c.shots[B], c.goals[B], c.moves[B] = 2, 1, 2
    c.transitions[B, A] = 2
    before = solve(c).xt.reshape(-1)[B]
    c.moves[B] += 10
    c.transitions[B, B] += 10
    assert solve(c).xt.reshape(-1)[B] == pytest.approx(before)


def test_mirrored_counts_are_symmetric() -> None:
    c = Counts.zero()
    c.shots[zone((115, 5))], c.goals[zone((115, 5))] = 3, 1
    xt = solve(c.mirrored()).xt
    assert np.allclose(xt, xt[::-1])
    assert xt[0, -1] == pytest.approx(1 / 3)


def test_counting_events(tmp_path: Path) -> None:
    events = [
        ev("pass", (5, 5), end_location=[115, 40], outcome="complete"),
        ev("pass", (5, 5), end_location=[60, 40], outcome="failure"),  # lost: a move, no transition
        ev("carry", (5, 5), end_location=[6, 5]),
        ev("shot", (115, 40), shot={"xg": 0.5, "outcome": "goal"}),
        ev("shot", (108, 40), shot={"xg": 0.78, "outcome": "goal"}),  # a penalty
        ev("shot", (115, 40), shot={"xg": 0.1, "outcome": "goal"}, period=5),  # the shootout
        ev("pressure", (5, 5)),
    ]
    path = tmp_path / "1.jsonl"
    path.write_text("".join(json.dumps({"kind": "event", "event": e}) + "\n" for e in events))
    path.write_text(path.read_text() + json.dumps({"kind": "match_end", "marker": {}}) + "\n")
    c = count_file(path)
    assert (c.moves[A], c.transitions[A].sum(), c.transitions[A, B], c.transitions[A, A]) == (
        3,
        2,
        1,
        1,
    )
    assert (c.shots.sum(), c.goals.sum()) == (1, 1)
    assert is_penalty(events[4]) and not is_penalty(events[3])


def test_score_grid() -> None:
    xt = np.zeros(8 * GRID_COLS)
    xt[B] = 0.5
    outcomes = [(B, True), (B, False), (A, False), (A, False)]
    s = score_grid(xt, outcomes)
    assert s.goal_rate == 0.25 and s.actions == 4
    assert s.brier == pytest.approx((0.25 + 0.25 + 1e-12 * 2) / 4)
    assert s.calibration == pytest.approx(1.0, abs=1e-5)
    assert s.brier_skill == pytest.approx(1 - s.brier / 0.1875)
    assert score_grid(xt, outcomes, min_col=8).actions == 2
