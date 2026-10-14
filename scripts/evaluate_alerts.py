"""Measures whether the alerts predict goals.

    make evaluate                                          # every 2022 World Cup match
    cd engine && uv run python ../scripts/evaluate_alerts.py --sample 20 --seed 7

Replays exported feeds (make export) through the engine offline, exactly as it
runs live (see engine.backtest), then compares each alert with the goals that
followed:

- how often the alerted team scores in the next 5 or 10 minutes, against how
  often a team scores in any 5 or 10 minutes of play (the lift: 1.0 is no
  better than chance);
- how often the opponent scores in the next 10 minutes instead;
- how often the alert comes within 5 minutes after the team scored, so it
  reacts rather than predicts;
- how many goals the scorer had an alert for in the 10 minutes before.

Only play after 15 minutes counts (the momentum detector's warm-up), and not
the penalty shootout. The 64 World Cup matches replay in a few seconds; they
have 172 goals, about 150 after the warm-up.

Runs in the engine's environment, which it imports.
"""

import argparse
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.backtest import Replay, replay_files
from engine.metrics.xt import DEFAULT_GRID_PATH

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEEDS = ROOT / "data" / "feeds"
DEFAULT_COMPETITION = "FIFA World Cup"
DEFAULT_SEASON = "2022"
DEFAULT_SEED = 2022
HORIZONS_MIN = (5, 10)
REACTIVE_MIN = 5
WARMUP_S = 15 * 60
STEP_S = 30  # the detectors' tick, for sampling the base rate
TYPES = ("momentum_shift", "goal_threat", "control_shift")


@dataclass(frozen=True)
class Match:
    """What happened in a match, in seconds of play since kick-off."""

    teams: tuple[int, int]
    goals: list[tuple[int, float]]
    """(team_id, play_s) of each goal, for the team it counts for."""
    end_s: float

    @classmethod
    def of(cls, r: Replay) -> "Match":
        return cls(r.team_ids, [(g.team_id, g.play_s) for g in r.goals], r.end_play_s)

    def opponent(self, team_id: int) -> int:
        return self.teams[1] if team_id == self.teams[0] else self.teams[0]

    def scores(self, team_id: int, after_s: float, minutes: int) -> bool:
        return any(t == team_id and after_s < s <= after_s + minutes * 60 for t, s in self.goals)

    def scored(self, team_id: int, before_s: float, minutes: int) -> bool:
        return any(t == team_id and before_s - minutes * 60 <= s <= before_s for t, s in self.goals)


@dataclass(frozen=True)
class Outcome:
    """What followed an alert."""

    type: str
    scores: tuple[bool, ...]  # within each of HORIZONS_MIN
    opponent_scores: bool  # within the longest horizon
    reactive: bool


@dataclass
class Evaluation:
    outcomes: list[Outcome]
    base: list[tuple[bool, ...]]  # each team at each tick: did it score within each horizon
    goals: int
    warned: dict[str, int]  # goals with an alert of a type (or "any") for the scorer before

    def add(self, r: Replay) -> None:
        match = Match.of(r)
        timed = [(a.alert.type.value, a.alert.team_id, a.play_s) for a in r.alerts]
        longest = max(HORIZONS_MIN)
        for type, team, at in timed:
            self.outcomes.append(
                Outcome(
                    type,
                    tuple(match.scores(team, at, h) for h in HORIZONS_MIN),
                    match.scores(match.opponent(team), at, longest),
                    match.scored(team, at, REACTIVE_MIN),
                )
            )
        t = float(WARMUP_S)
        while t < match.end_s:
            for team in match.teams:
                self.base.append(tuple(match.scores(team, t, h) for h in HORIZONS_MIN))
            t += STEP_S
        for scorer, scored_s in match.goals:
            if scored_s < WARMUP_S:
                continue
            self.goals += 1
            before = {
                type
                for type, team, at in timed
                if team == scorer and scored_s - longest * 60 <= at < scored_s
            }
            for type in before | ({"any"} if before else set()):
                self.warned[type] = self.warned.get(type, 0) + 1

    def report(self) -> str:
        base = [rate([b[i] for b in self.base]) for i in range(len(HORIZONS_MIN))]
        longest = max(HORIZONS_MIN)
        header = "alert".ljust(16) + "count".rjust(6)
        for h in HORIZONS_MIN:
            header += f"scores in {h}'".rjust(15) + "lift".rjust(6)
        header += f"opponent in {longest}'".rjust(17) + "just after scoring".rjust(20)
        lines = [
            f"{self.goals} goals after 15'. A team scores in a given "
            + " and ".join(f"{h}' {percent(r)}" for h, r in zip(HORIZONS_MIN, base, strict=True))
            + " of the time.",
            "",
            header,
        ]
        for type in (*TYPES, None):
            rows = [o for o in self.outcomes if type is None or o.type == type]
            cells = f"{type or 'all':16}{len(rows):>6}"
            for i, b in enumerate(base):
                r = rate([o.scores[i] for o in rows])
                cells += f"{percent(r):>15}{ratio(r, b):>6}"
            cells += f"{percent(rate([o.opponent_scores for o in rows])):>17}"
            cells += f"{percent(rate([o.reactive for o in rows])):>20}"
            lines.append(cells)
        lines += ["", f"Goals the scorer had an alert for in the {longest}' before:"]
        for type in (*TYPES, "any"):
            n = self.warned.get(type, 0)
            lines.append(f"  {type:16}{n:>4}  {percent(n / self.goals if self.goals else None)}")
        return "\n".join(lines)


def rate(hits: list[bool]) -> float | None:
    return sum(hits) / len(hits) if hits else None


def percent(r: float | None) -> str:
    return "-" if r is None else f"{r:.1%}"


def ratio(r: float | None, base: float | None) -> str:
    return "-" if r is None or not base else f"{r / base:.1f}"


def choose(feeds: Path, competition: str, season: str) -> list[dict[str, Any]]:
    """The exported matches of a competition's season, by match id."""
    listing = feeds / "matches.json"
    if not listing.exists():
        raise SystemExit(f"evaluate alerts: no {listing}; run: make export")
    infos: list[dict[str, Any]] = json.loads(listing.read_text())["matches"]
    return sorted(
        (
            m
            for m in infos
            if (not competition or m["competition"] == competition)
            and (not season or m["season"] == season)
        ),
        key=lambda m: int(m["match_id"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument(
        "--feeds", type=Path, default=DEFAULT_FEEDS, metavar="DIR", help="exported feeds"
    )
    parser.add_argument(
        "--competition",
        default=DEFAULT_COMPETITION,
        help=f"which matches (default {DEFAULT_COMPETITION!r}; '' for any)",
    )
    parser.add_argument(
        "--season", default=DEFAULT_SEASON, help=f"default {DEFAULT_SEASON!r}; '' for any"
    )
    parser.add_argument(
        "--sample", type=int, metavar="N", help="replay only N of them, picked by --seed"
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="for --sample")
    parser.add_argument("--workers", type=int, help="processes (default: one per CPU)")
    parser.add_argument(
        "--xt-grid", type=Path, default=DEFAULT_GRID_PATH, metavar="FILE", help="xT grid JSON"
    )
    args = parser.parse_args()

    chosen = choose(args.feeds, args.competition, args.season)
    if not chosen:
        raise SystemExit("evaluate alerts: no matches chosen; run: make fetch-data export")
    if args.sample is not None and args.sample < len(chosen):
        chosen = random.Random(args.seed).sample(chosen, args.sample)
    print(f"Replaying {len(chosen)} matches", file=sys.stderr, flush=True)
    paths = [args.feeds / f"{m['match_id']}.jsonl" for m in chosen]
    evaluation = Evaluation([], [], 0, {})
    for r in replay_files(paths, args.xt_grid, workers=args.workers):
        evaluation.add(r)
    print(evaluation.report())


if __name__ == "__main__":
    main()
