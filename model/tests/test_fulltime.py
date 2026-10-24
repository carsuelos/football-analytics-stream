from pathlib import Path

import numpy as np
import pytest
from engine.detectors.fulltime import minutes_left
from engine.features import FEATURE_NAMES

from model.dataset import Dataset, fulltime_labels
from model.fulltime import independent, left, opponents, symmetric


def test_fulltime_labels_count_goals_after_the_tick_until_the_end_of_regulation() -> None:
    play_s = np.array([100.0, 100.0, 5000.0, 5000.0, 5600.0, 5600.0])
    team_id = np.array([1, 2, 1, 2, 1, 2])
    # Team 2 at 5000 (at the tick, so not after it), team 1 at 5500, team 2 in extra time.
    goals = [(2, 5000.0), (1, 5500.0), (2, 5800.0)]
    ft = fulltime_labels(play_s, team_id, goals, end_s=5700.0)
    assert ft[:, 0].tolist() == [True, True, True, False, False, False]
    assert ft[:, 1].tolist() == [True, True, True, True, False, False]


def test_left_matches_the_engine() -> None:
    residuals = (-2.6, -1.0, 0.0, 1.5, 3.0)
    minute = np.array([20.0, 85.0, 97.5, 99.0, 104.0])
    end = np.array([99.0, 99.0, 99.0, 101.0, 99.0])
    want = [minutes_left(m, e, residuals) for m, e in zip(minute, end, strict=True)]
    assert left(minute, end, residuals) == pytest.approx(want)


def two_teams(n_ticks: int = 3) -> Dataset:
    n = 2 * n_ticks
    play_s = np.repeat(np.arange(n_ticks) * 30.0 + 900, 2)[::-1].copy()
    return Dataset(
        np.zeros((n, len(FEATURE_NAMES))),
        np.zeros((n, 2), dtype=bool),
        np.zeros(n, dtype=np.int64),
        np.tile([7, 9], n_ticks),
        play_s,
    )


def test_each_row_is_paired_with_the_other_team_at_the_same_tick() -> None:
    d = two_teams()
    opp = opponents(d)
    assert (d.play_s[opp] == d.play_s).all() and (d.team_id[opp] != d.team_id).all()
    p = np.array([0.2, 0.4, 0.1, 0.3, 0.5, 0.5])
    assert symmetric(p, opp)[:2] == pytest.approx([0.3, 0.3])
    assert independent(p, opp)[0] == pytest.approx(1 - 0.8 * 0.6)


def test_the_full_time_labels_are_saved(tmp_path: Path) -> None:
    d = two_teams()
    d = Dataset(d.x, d.y, d.match_id, d.team_id, d.play_s, ft=np.ones((len(d), 2), dtype=bool))
    d.save(tmp_path / "d.npz")
    back = Dataset.load(tmp_path / "d.npz")
    assert back.ft.all() and back.subset(np.array([0, 1])).ft.shape == (2, 2)
