# /// script
# requires-python = ">=3.13"
# ///
"""End-to-end smoke test: replays matches through the simulator and engine, and checks the results.

    uv run scripts/smoke_test.py                    # the 2022 World Cup final
    uv run scripts/smoke_test.py --sample           # and 10 random other matches
    uv run scripts/smoke_test.py --sample 5 --seed 42
    uv run scripts/smoke_test.py --match 3857256    # another downloaded match
    uv run scripts/smoke_test.py --external http://localhost:3000   # a running stack

Builds and starts the simulator (delivering events up to 3s late, so the
engine has to reorder them) and the engine, on their own ports so a dev setup
can keep running. Each match is played in turn at 1000x through the engine's
/api/control until the engine reports it ended, then its metrics and alerts
are checked: for any match, that they are consistent, and for the final, that
they tell the story of the match. Needs `make fetch-data`, Go and uv. Exits 1
if a check fails, and then keeps the processes' logs. A failing --sample is
reproduced with the --seed it printed.

With --external, nothing is built or started: the checks run against an
engine API that is already up (such as `make up`, through the dashboard's
proxy), and its logs are not checked.
"""

import argparse
import json
import os
import random
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FINAL = 3869685
SPEED = 1000
JITTER = "3s"
WINDOWS = {300, 600}
READY_TIMEOUT_S = 120  # the first `uv run` may have to install the engine
MATCH_TIMEOUT_S = 60  # a match with a shootout takes about 10s at 1000x

type Json = dict[str, Any]


class SmokeError(Exception):
    """The stack could not be started or driven (as opposed to a failed check)."""


class Api:
    """The engine's API."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def get(self, path: str) -> Any:
        return self._send(urllib.request.Request(self.base + path))

    def control(self, command: str, **fields: Any) -> Json:
        body = json.dumps({"schema_version": 1, "command": command, **fields}).encode()
        request = urllib.request.Request(
            self.base + "/api/control", body, {"Content-Type": "application/json"}
        )
        reply: Json = self._send(request)
        return reply

    @staticmethod
    def _send(request: urllib.request.Request) -> Any:
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            raise SmokeError(f"{request.full_url}: {e.code} {e.read().decode()}") from e


@dataclass
class Process:
    name: str
    popen: subprocess.Popen[bytes]
    log: Path
    log_read: int = 0  # bytes of the log already checked for errors

    def check_running(self) -> None:
        if self.popen.poll() is not None:
            raise SmokeError(f"the {self.name} exited with {self.popen.returncode}")

    def stop(self) -> None:
        # Each process leads its own group, so `uv run`'s child is stopped too.
        if self.popen.poll() is None:
            os.killpg(self.popen.pid, signal.SIGINT)
            try:
                self.popen.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(self.popen.pid, signal.SIGKILL)
                self.popen.wait()


@contextmanager
def stack(sim_port: int, engine_port: int, logs: Path) -> Iterator[list[Process]]:
    """Runs the simulator and the engine until the block ends."""
    for port in (sim_port, engine_port):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                raise SmokeError(f"port {port} is in use (see --sim-port and --engine-port)")

    print("Building the simulator…", flush=True)
    sim_bin = logs / "simulator"
    subprocess.run(
        ["go", "build", "-o", sim_bin, "./cmd/simulator"], cwd=ROOT / "simulator", check=True
    )

    def start(name: str, args: list[str | Path], cwd: Path) -> Process:
        log = logs / f"{name}.log"
        with log.open("wb") as out:
            popen = subprocess.Popen(
                args, cwd=cwd, stdout=out, stderr=subprocess.STDOUT, start_new_session=True
            )
        return Process(name, popen, log)

    processes: list[Process] = []
    try:
        processes.append(
            start(
                "simulator",
                [
                    sim_bin,
                    "-addr",
                    f"127.0.0.1:{sim_port}",
                    "-data",
                    ROOT / "data" / "statsbomb",
                    "-jitter",
                    JITTER,
                ],
                ROOT,
            )
        )
        processes.append(
            start(
                "engine",
                [
                    "uv",
                    "run",
                    "engine",
                    "--simulator",
                    f"http://127.0.0.1:{sim_port}",
                    "--port",
                    str(engine_port),
                ],
                ROOT / "engine",
            )
        )
        yield processes
    finally:
        for p in reversed(processes):
            p.stop()


def wait_ready(api: Api, processes: list[Process]) -> list[Json]:
    """Waits until the engine can reach the simulator, and returns the match list."""
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        for p in processes:
            p.check_running()
        try:
            matches: list[Json] = api.get("/api/matches")["matches"]
            return matches
        except (SmokeError, OSError):
            if time.monotonic() > deadline:
                raise SmokeError(f"the engine was not ready after {READY_TIMEOUT_S}s") from None
            time.sleep(0.5)


@dataclass
class Replay:
    match: Json
    status: Json
    metrics: list[Json]
    alerts: list[Json]
    seconds: float


def replay(api: Api, processes: list[Process], match: Json) -> Replay:
    """Plays a match at full speed and returns what the engine made of it."""
    match_id = match["match_id"]
    started = time.monotonic()
    generation = api.get("/api/status")["generation"]
    api.control("load_match", match_id=match_id)
    api.control("set_speed", speed=SPEED)
    api.control("play")
    while True:
        for p in processes:
            p.check_running()
        status: Json = api.get("/api/status")
        # Loading starts a new generation; until then the status is the previous match's.
        new = status["generation"] > generation and status.get("match_id") == match_id
        if new and status["state"] == "ended":
            break
        if time.monotonic() - started > MATCH_TIMEOUT_S:
            raise SmokeError(
                f"match {match_id} did not end within {MATCH_TIMEOUT_S}s: {status['state']}"
                f" at {at(status) if 'period' in status else 'the start'}"
            )
        time.sleep(0.2)
    return Replay(
        match, status, api.get("/api/metrics"), api.get("/api/alerts"), time.monotonic() - started
    )


type Time = tuple[int, float]  # period, match clock in seconds


def clock(period: int, minute: int, second: int) -> Time:
    return period, minute * 60 + second


def when(x: Json) -> Time:
    return x["period"], x["match_clock_s"]


def at(x: Json | Time) -> str:
    """Where something happened, e.g. "P2 82:27"."""
    period, clock_s = when(x) if isinstance(x, dict) else x
    m, s = divmod(int(clock_s), 60)
    return f"P{period} {m}:{s:02}"


def general_checks(r: Replay) -> list[str]:
    """What should hold for any match."""
    problems = []
    match_id = r.match["match_id"]
    teams = {r.match["home_team"]["id"], r.match["away_team"]["id"]}

    seen = {t["id"] for t in r.status.get("teams", [])}
    if seen != teams:
        problems.append(f"the engine saw teams {sorted(seen)}, not {sorted(teams)}")
    for counter in ("late_dropped", "duplicates", "buffered"):
        if r.status[counter]:
            problems.append(f"{counter} is {r.status[counter]}")

    def report(bad: list[Json], what: str) -> None:
        if bad:
            problems.append(f"{len(bad)} {what}, e.g. at {at(bad[0])}")

    m = r.metrics
    if {s["window_s"] for s in m} != WINDOWS:
        problems.append(f"snapshot windows are {sorted({s['window_s'] for s in m})}")
    report([s for s in m if s["match_id"] != match_id], "snapshots are for another match")
    report(
        [s for s in m if {t["team_id"] for t in s["teams"]} != teams],
        "snapshots have the wrong teams",
    )
    report(
        [s for s in m if abs(sum(t["field_tilt"] for t in s["teams"]) - 1) > 1e-9],
        "snapshots' field tilts don't add up to 1",
    )
    report(
        [s for s in m if any(t["pressure_index"] < 0 for t in s["teams"])],
        "snapshots have a negative pressure index",
    )
    for window_s in WINDOWS:
        # Not offset order: jittered events are numbered in the order they arrive.
        times = [when(s) for s in m if s["window_s"] == window_s]
        if times != sorted(times):
            problems.append(f"{window_s}s snapshots are out of match-time order")

    a = r.alerts
    report([x for x in a if x["match_id"] != match_id], "alerts are for another match")
    report([x for x in a if x["team_id"] not in teams], "alerts are for another team")
    report([x for x in a if x["value"] < x["threshold"]], "alerts are below their threshold")
    if len({x["id"] for x in a}) != len(a):
        problems.append("alert ids are not unique")
    return problems


ARGENTINA, FRANCE = 779, 771


def final_checks(r: Replay) -> list[str]:
    """What happened in the 2022 World Cup final: Argentina 3-3 France, 4-2 on penalties."""
    problems = []
    home, away = r.match["home_team"], r.match["away_team"]
    if (home["id"], away["id"]) != (ARGENTINA, FRANCE):
        problems.append(
            f"home and away are {home['name']} and {away['name']}, not Argentina and France"
        )
    if r.status["period"] != 5:
        problems.append(f"the match ended in period {r.status['period']}, not in the shootout")

    first_half = [s for s in r.metrics if s["window_s"] == 600 and s["period"] == 1]
    tilts = [t["field_tilt"] for s in first_half for t in s["teams"] if t["team_id"] == ARGENTINA]
    tilt = mean(tilts) if tilts else 0.0
    if tilt <= 0.5:
        problems.append(f"Argentina's first-half 10' field tilt averaged {tilt:.0%}, not over 50%")

    # The goal threat should warn before a team scores, not after: before France's first
    # goal and Messi's extra-time goal, each counted from the previous goal.
    for team, name, since, goal in (
        (FRANCE, "France", clock(1, 35, 22), clock(2, 79, 24)),
        (ARGENTINA, "Argentina", clock(2, 80, 59), clock(4, 107, 58)),
    ):
        if not any(
            a["type"] == "goal_threat" and a["team_id"] == team and since < when(a) < goal
            for a in r.alerts
        ):
            problems.append(f"no goal threat for {name} before their goal at {at(goal)}")
    return problems


EXPECTATIONS: dict[int, Callable[[Replay], list[str]]] = {FINAL: final_checks}


def log_errors(processes: list[Process]) -> list[str]:
    """Errors the processes logged since the last call, though they kept running."""
    errors = []
    for p in processes:
        with p.log.open("rb") as f:
            f.seek(p.log_read)
            new = f.read()
        # Leave a partly written last line for the next call.
        complete = new[: new.rfind(b"\n") + 1]
        p.log_read += len(complete)
        for line in complete.decode(errors="replace").splitlines():
            if "ERROR" in line or "Traceback" in line or "panic:" in line:
                errors.append(f"{p.name}: {line.strip()}")
    return errors


def choose(args: argparse.Namespace, downloaded: dict[int, Json]) -> list[Json]:
    """The matches to replay: --match (or the final), then a --sample of the others."""
    chosen = args.match or [FINAL]
    missing = [m for m in chosen if m not in downloaded]
    if missing:
        raise SmokeError(f"match {missing[0]} is not downloaded (see make fetch-data)")
    if args.sample:
        others = sorted(downloaded.keys() - set(chosen))
        seed = args.seed if args.seed is not None else random.randrange(1_000_000)
        n = min(args.sample, len(others))
        print(f"Sampling {n} of {len(others)} other matches (--seed {seed})", flush=True)
        chosen = chosen + random.Random(seed).sample(others, n)
    return [downloaded[m] for m in chosen]


def check(api: Api, processes: list[Process], match: Json) -> bool:
    """Replays a match and prints how it went. Returns whether all checks passed."""
    match_id = match["match_id"]
    name = f"{match['home_team']['name']} v {match['away_team']['name']} ({match_id})"
    r = replay(api, processes, match)
    expected = EXPECTATIONS[match_id](r) if match_id in EXPECTATIONS else []
    problems = general_checks(r) + expected + log_errors(processes)
    print(
        f"{'✗' if problems else '✓'} {name}: ended after {r.seconds:.1f}s,"
        f" {len(r.metrics)} snapshots, {len(r.alerts)} alerts",
        flush=True,
    )
    for problem in problems:
        print(f"    {problem}")
    return not problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--match", type=int, action="append", help="match id, repeatable (default: the final)"
    )
    parser.add_argument(
        "--sample",
        type=int,
        nargs="?",
        const=10,
        default=0,
        metavar="N",
        help="also replay N (default 10) random other downloaded matches",
    )
    parser.add_argument("--seed", type=int, help="seed for --sample (default: random, printed)")
    parser.add_argument("--sim-port", type=int, default=18080)
    parser.add_argument("--engine-port", type=int, default=18000)
    parser.add_argument(
        "--external",
        metavar="URL",
        help="check a running stack at this base URL instead of starting one",
    )
    args = parser.parse_args()

    logs = Path(tempfile.mkdtemp(prefix="smoke-"))
    failed = True
    try:
        running: AbstractContextManager[list[Process]] = (
            nullcontext([]) if args.external else stack(args.sim_port, args.engine_port, logs)
        )
        with running as processes:
            api = Api(args.external or f"http://127.0.0.1:{args.engine_port}")
            downloaded = {m["match_id"]: m for m in wait_ready(api, processes)}
            # One pair of processes for every match, so switching matches is tested too.
            passed = [check(api, processes, m) for m in choose(args, downloaded)]
            if len(passed) > 1:
                print(f"{sum(passed)} of {len(passed)} matches passed")
            failed = not all(passed)
    except SmokeError as e:
        print(f"smoke test: {e}", file=sys.stderr)
    except KeyboardInterrupt:
        print("smoke test: interrupted", file=sys.stderr)
        sys.exit(130)
    finally:
        if failed and any(logs.glob("*.log")):
            print(f"Logs: {logs}", file=sys.stderr)
        else:
            shutil.rmtree(logs)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
