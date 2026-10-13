# /// script
# requires-python = ">=3.13"
# ///
"""Measures whether the alerts predict goals.

    uv run scripts/evaluate_alerts.py                     # 20 matches, the same ones every run
    uv run scripts/evaluate_alerts.py --sample 5 --seed 7

Replays matches through the simulator and engine as the smoke test does, then
compares each alert with the goals in StatsBomb's events:

- how often the alerted team scores in the next 5 or 10 minutes, against how
  often a team scores in any 5 or 10 minutes of play (the lift: 1.0 is no
  better than chance);
- how often the opponent scores in the next 10 minutes instead;
- how often the alert comes within 5 minutes after the team scored, so it
  reacts rather than predicts;
- how many goals the scorer had an alert for in the 10 minutes before.

Only play after 15 minutes counts (the momentum detector's warm-up), and not
the penalty shootout. Twenty matches give about 50 goals, enough to compare
runs but not to tune against; Phase 3 evaluates every match.
"""

import argparse
import json
import random
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from smoke_test import ROOT, Api, Json, SmokeError, replay, stack, wait_ready

DEFAULT_SAMPLE = 20
DEFAULT_SEED = 2022
HORIZONS_MIN = (5, 10)
REACTIVE_MIN = 5
WARMUP_S = 15 * 60
STEP_S = 30  # the detectors' tick, for sampling the base rate
PERIOD_START_S = {1: 0, 2: 45 * 60, 3: 90 * 60, 4: 105 * 60}  # as the simulator's match clock
TYPES = ("momentum_shift", "goal_threat", "control_shift")


@dataclass(frozen=True)
class Goal:
    team_id: int
    play_s: float


@dataclass(frozen=True)
class Match:
    """What happened in a match, in seconds of play since kick-off."""

    teams: tuple[int, int]
    goals: list[Goal]
    period_play_s: dict[int, float]
    """Play before each period started."""
    end_s: float

    @classmethod
    def load(cls, info: Json) -> "Match":
        path = ROOT / "data" / "statsbomb" / "events" / f"{info['match_id']}.json"
        events = [e for e in json.loads(path.read_text()) if e["period"] in PERIOD_START_S]
        length = {
            p: max(seconds(e) for e in events if e["period"] == p)
            for p in sorted({e["period"] for e in events})
        }
        before, total = {}, 0.0
        for period, s in length.items():
            before[period] = total
            total += s
        goals = [
            Goal(e["team"]["id"], before[e["period"]] + seconds(e))
            for e in events
            if (e["type"]["name"] == "Shot" and e["shot"]["outcome"]["name"] == "Goal")
            or e["type"]["name"] == "Own Goal For"
        ]
        teams = (info["home_team"]["id"], info["away_team"]["id"])
        return cls(teams, goals, before, total)

    def play_s(self, alert: Json) -> float:
        period: int = alert["period"]
        clock_s: float = alert["match_clock_s"]
        return self.period_play_s[period] + clock_s - PERIOD_START_S[period]

    def opponent(self, team_id: int) -> int:
        return self.teams[1] if team_id == self.teams[0] else self.teams[0]

    def scores(self, team_id: int, after_s: float, minutes: int) -> bool:
        return any(
            g.team_id == team_id and after_s < g.play_s <= after_s + minutes * 60
            for g in self.goals
        )

    def scored(self, team_id: int, before_s: float, minutes: int) -> bool:
        return any(
            g.team_id == team_id and before_s - minutes * 60 <= g.play_s <= before_s
            for g in self.goals
        )


def seconds(event: Json) -> float:
    h, m, s = event["timestamp"].split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


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

    def add(self, match: Match, alerts: list[Json]) -> None:
        timed = [
            (a["type"], a["team_id"], match.play_s(a))
            for a in alerts
            if a["period"] in PERIOD_START_S
        ]
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
        for goal in match.goals:
            if goal.play_s < WARMUP_S:
                continue
            self.goals += 1
            before = {
                type
                for type, team, at in timed
                if team == goal.team_id and goal.play_s - longest * 60 <= at < goal.play_s
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--sample",
        type=int,
        default=DEFAULT_SAMPLE,
        metavar="N",
        help=f"how many downloaded matches to replay (default {DEFAULT_SAMPLE})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"which matches (default {DEFAULT_SEED}, the same every run)",
    )
    parser.add_argument("--sim-port", type=int, default=18080)
    parser.add_argument("--engine-port", type=int, default=18000)
    args = parser.parse_args()

    logs = Path(tempfile.mkdtemp(prefix="evaluate-"))
    failed = True
    try:
        with stack(args.sim_port, args.engine_port, logs) as processes:
            api = Api(f"http://127.0.0.1:{args.engine_port}")
            downloaded = sorted(wait_ready(api, processes), key=lambda m: m["match_id"])
            n = min(args.sample, len(downloaded))
            chosen = random.Random(args.seed).sample(downloaded, n)
            print(f"Replaying {n} of {len(downloaded)} matches (--seed {args.seed})", flush=True)
            evaluation = Evaluation([], [], 0, {})
            for i, info in enumerate(chosen, 1):
                r = replay(api, processes, info)
                evaluation.add(Match.load(info), r.alerts)
                print(
                    f"  {i}/{n} {info['home_team']['name']} v {info['away_team']['name']}:"
                    f" {len(r.alerts)} alerts",
                    flush=True,
                )
        print()
        print(evaluation.report())
        failed = False
    except SmokeError as e:
        print(f"evaluate alerts: {e}", file=sys.stderr)
    except KeyboardInterrupt:
        print("evaluate alerts: interrupted", file=sys.stderr)
        sys.exit(130)
    finally:
        if failed and any(logs.glob("*.log")):
            print(f"Logs: {logs}", file=sys.stderr)
        else:
            shutil.rmtree(logs)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
