import io
import json
from pathlib import Path

import pytest

from engine.market_tape import main, read, replay, summarize, write_prices

FIXTURES = Path(__file__).resolve().parents[2] / "schema" / "fixtures" / "valid" / "market_tape"
GAME = "epl-2026-10-24-chelsea-tottenham"


@pytest.fixture
def tape(tmp_path: Path) -> Path:
    """A keyframe, then a change: Kalshi's Over 1.5 moves, Polymarket's draw goes."""
    path = tmp_path / "2026-10-24" / "epl.jsonl"
    path.parent.mkdir()
    lines = [
        json.dumps(json.loads((FIXTURES / f).read_text())) for f in ("keyframe.json", "change.json")
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


def test_replay_applies_each_change_to_the_keyframe(tape: Path) -> None:
    states = [(g.clock, dict(g.quotes)) for g in replay(read([tape]))]
    assert [clock for clock, _ in states] == ["63'", "64'"]
    first, second = states[0][1], states[1][1]
    assert set(first) == {
        ("total-over-1.5", "kalshi"),
        ("total-over-1.5", "novig"),
        ("result-draw", "polymarket"),
    }
    assert first[("total-over-1.5", "kalshi")].ask == 0.48
    assert set(second) == {("total-over-1.5", "kalshi"), ("total-over-1.5", "novig")}
    assert second[("total-over-1.5", "kalshi")].ask == 0.47


def test_best_is_the_lowest_ask_plus_fee(tape: Path) -> None:
    *_, g = replay(read([tape]))
    # Kalshi 0.47 + 0.0174 against Novig 0.49 + 0.015.
    best = g.best("total-over-1.5")
    assert best is not None
    assert best[0] == "kalshi"
    assert best[1] == pytest.approx(0.4874)
    assert g.best("result-draw") is None


def test_a_change_before_any_keyframe_is_skipped(tape: Path) -> None:
    *_, change = read([tape])
    assert list(replay([change])) == []


def test_summary_and_prices(tape: Path, capsys: pytest.CaptureFixture[str]) -> None:
    [s] = summarize(read([tape]))
    assert (s.home, s.away, s.lines, s.state, s.score, s.contracts) == (
        "Chelsea",
        "Tottenham",
        2,
        "live",
        "0-1",
        2,
    )
    assert s.venues == ["kalshi", "novig", "polymarket"]

    out = io.StringIO()
    assert write_prices(read([tape]), GAME, "total-over-1.5", out) == 2
    rows = out.getvalue().splitlines()
    assert (
        rows[0] == "t,state,clock,score,kalshi_ask,polymarket_ask,novig_ask,best_all_in,best_venue"
    )
    assert rows[2].endswith(",live,64',0-1,0.47,,0.49,0.4874,kalshi")

    main([str(tape.parent.parent)])
    assert json.loads(capsys.readouterr().out)["game_id"] == GAME
