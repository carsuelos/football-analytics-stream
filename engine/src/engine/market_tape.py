"""Market tapes: the prices the markets service recorded, read back for replay.

    make up                                            # records to data/markets while it runs
    uv run python -m engine.market_tape ../data/markets                 # one line per game
    uv run python -m engine.market_tape ../data/markets/2026-10-25 \\
        --game epl-2026-10-25-crystal-palace-newcastle --contract total-over-2.5
                                                       # that contract's prices, as CSV

A tape is JSON lines (schema/jsonschema/market_tape.schema.json), one file per
league and UTC day. Each game starts with a keyframe holding its whole state;
the lines after it carry only what changed, so `replay` applies them in order
and yields the game as it stood after each line: the state, score and clock,
and every venue's bid and ask (with its fee) for every contract. That's what a
paper-trading strategy replays against: the prices it could really have had.
"""

import argparse
import csv
import json
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TextIO

from engine.schema.market_board_schema import GameState, MarketScore
from engine.schema.market_tape_schema import MarketTapeRecord, TapeContract, TapeQuote

VENUES = ("kalshi", "polymarket", "novig")


@dataclass
class TapeGame:
    """A game as the tape last described it."""

    game_id: str
    league: str
    home: str
    away: str
    kickoff: datetime | None
    t: datetime
    state: GameState
    score: MarketScore | None = None
    clock: str | None = None
    contracts: dict[str, TapeContract] = field(default_factory=dict)
    # By (contract key, venue).
    quotes: dict[tuple[str, str], TapeQuote] = field(default_factory=dict)

    def best(self, contract: str) -> tuple[str, float] | None:
        """The venue with the lowest all-in price (ask + fee) for a contract, and that price."""
        offers = [
            (q.ask + (q.fee or 0.0), venue)
            for (key, venue), q in self.quotes.items()
            if key == contract and q.ask is not None
        ]
        if not offers:
            return None
        price, venue = min(offers)
        return venue, price


def tape_paths(paths: Iterable[Path]) -> list[Path]:
    """The .jsonl files at the paths, directories searched recursively, in time order."""
    out: list[Path] = []
    for p in paths:
        out.extend(sorted(p.rglob("*.jsonl")) if p.is_dir() else [p])
    return out


def read(paths: Iterable[Path]) -> Iterator[MarketTapeRecord]:
    """Every record in the files, in order."""
    for path in paths:
        with path.open() as f:
            for line in f:
                if line.strip():
                    yield MarketTapeRecord.model_validate_json(line)


def replay(records: Iterable[MarketTapeRecord]) -> Iterator[TapeGame]:
    """Each game as it stood after each of its lines.

    The same TapeGame object is updated and yielded again for a game's later
    lines; copy what you keep. Lines before a game's first keyframe (a tape
    cut mid-game) are skipped.
    """
    games: dict[str, TapeGame] = {}
    for r in records:
        g = games.get(r.game_id)
        if r.keyframe:
            g = TapeGame(
                game_id=r.game_id,
                league=r.league.value,
                home=r.home or "",
                away=r.away or "",
                kickoff=r.kickoff,
                t=r.t,
                state=r.state,
                contracts={c.key: c for c in r.contracts or []},
            )
            games[r.game_id] = g
        elif g is None:
            continue
        g.t, g.state, g.score, g.clock = r.t, r.state, r.score, r.clock
        for q in r.quotes:
            g.quotes[(q.contract, q.venue.value)] = q
        for gone in r.gone or []:
            g.quotes.pop((gone.contract, gone.venue.value), None)
        yield g


@dataclass
class Summary:
    game_id: str
    home: str
    away: str
    first: datetime
    last: datetime
    lines: int
    state: str
    score: str | None
    contracts: int
    venues: list[str]


def summarize(records: Iterable[MarketTapeRecord]) -> list[Summary]:
    """One summary per game: what was recorded, and how it last stood."""
    out: dict[str, Summary] = {}
    for g in replay(records):
        s = out.get(g.game_id)
        if s is None:
            s = out[g.game_id] = Summary(g.game_id, g.home, g.away, g.t, g.t, 0, "", None, 0, [])
        s.last, s.lines, s.state = g.t, s.lines + 1, g.state.value
        s.score = f"{g.score.home}-{g.score.away}" if g.score else None
        s.contracts = len(g.contracts)
        s.venues = sorted({v for _, v in g.quotes} | set(s.venues))
    return list(out.values())


def write_prices(
    records: Iterable[MarketTapeRecord], game_id: str, contract: str, out: TextIO
) -> int:
    """A contract's prices over a game as CSV: each venue's ask, and the best all-in."""
    w = csv.writer(out)
    w.writerow(
        ["t", "state", "clock", "score", *(f"{v}_ask" for v in VENUES), "best_all_in", "best_venue"]
    )
    rows = 0
    for g in replay(r for r in records if r.game_id == game_id):
        asks = [g.quotes.get((contract, v)) for v in VENUES]
        best = g.best(contract)
        w.writerow(
            [
                g.t.isoformat(),
                g.state.value,
                g.clock or "",
                f"{g.score.home}-{g.score.away}" if g.score else "",
                *("" if q is None or q.ask is None else q.ask for q in asks),
                "" if best is None else round(best[1], 4),
                "" if best is None else best[0],
            ]
        )
        rows += 1
    return rows


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m engine.market_tape",
        description="Read the market tapes the markets service recorded: one JSON line per game, "
        "or with --game and --contract, that contract's prices as CSV.",
    )
    parser.add_argument(
        "paths", nargs="+", type=Path, metavar="PATH", help="tape files or directories of them"
    )
    parser.add_argument("--game", help="a game id, e.g. epl-2026-10-25-crystal-palace-newcastle")
    parser.add_argument(
        "--contract", help="a contract key, e.g. total-over-2.5 or team-home-over-0.5"
    )
    args = parser.parse_args(argv)
    paths = tape_paths(args.paths)
    if not paths:
        parser.error(
            "no tapes found (the markets service records to data/markets while `make up` runs)"
        )
    if bool(args.game) != bool(args.contract):
        parser.error("--game and --contract go together")
    if args.game:
        if write_prices(read(paths), args.game, args.contract, sys.stdout) == 0:
            parser.error(f"no lines for game {args.game}")
        return
    for s in summarize(read(paths)):
        d = s.__dict__ | {"first": s.first.isoformat(), "last": s.last.isoformat()}
        print(json.dumps(d), flush=True)


if __name__ == "__main__":
    main()
