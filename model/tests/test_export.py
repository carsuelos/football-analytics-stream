import json
import sys
from pathlib import Path

import numpy as np
import pytest
from engine.detectors import GoalModel

from model.export import ALERTS_PER_MATCH, HORIZON_MIN, engine_probabilities, export, main
from tests.test_train import synthetic


def test_the_engine_computes_what_scikit_learn_fitted() -> None:
    train = synthetic(10, seed=0)
    train.meta.update(xt_grid="g.json", xt_grid_sha256="0123456789ab")
    doc, shipped = export(train, synthetic(5, seed=1))
    assert shipped.features == train.names
    assert shipped.minute_knots == (60.0, 80.0, 85.0, 90.0, 95.0, 100.0)
    assert shipped.xt_grid_sha256 == "0123456789ab"
    assert shipped.base_rate == pytest.approx(train.label(HORIZON_MIN).mean())
    # The threshold gives about ALERTS_PER_MATCH alerts a match on the training set.
    p = engine_probabilities(shipped, train.x)
    assert shipped.base_rate < shipped.threshold < p.max()
    assert doc["training"]["matches"] == 10
    assert doc["test"]["auc"] > 0.6  # tilt_match carries the signal
    assert 0 < doc["test"]["alerts"] <= 5 * ALERTS_PER_MATCH * 2
    tilt = shipped.terms.index("tilt_match")
    assert np.argmax(np.abs(shipped.coef[: len(train.names)])) == tilt


def test_main_writes_a_model_the_engine_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synthetic(10, seed=0).save(tmp_path / "train.npz", xt_grid="g.json", xt_grid_sha256="abc")
    out = tmp_path / "goal_model.json"
    monkeypatch.setattr(sys, "argv", ["export", "--data", str(tmp_path), "--out", str(out)])
    main()  # no test.npz: no test scores
    m = GoalModel.load(out)
    assert m.xt_grid_sha256 == "abc"
    assert "test" not in json.loads(out.read_text())
