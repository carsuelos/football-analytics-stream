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
can keep running. Each match is broadcast in turn at 1000x through the engine's
/api/broadcast until the engine reports it ended, then its metrics and alerts
are checked: for any match, that they are consistent, and for the final, that
they tell the story of the match. The first match is then rewatched from
P2 60:00 through the engine's DVR (/api/control), which has to rebuild exactly
what it built live. Needs `make fetch-data`, Go and uv. Exits 1
if a check fails, and then keeps the processes' logs. A failing --sample is
reproduced with the --seed it printed.

With --external, nothing is built or started: the checks run against an
engine API that is already up (such as `make up`, through the dashboard's
proxy), and its logs are not checked. With --webhook too (the stack's
webhook_echo.py), it also checks that the notifier delivered every alert of
the run exactly once, rewatch included, as the engine raised it. If the
stack asks for a password (as the one in Azure does), set SMOKE_PASSWORD
(and SMOKE_USER, default viewer).
"""

import argparse
import base64
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
from collections import Counter
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
DELIVERY_TIMEOUT_S = 15

type Json = dict[str, Any]


class SmokeError(Exception):
    """The stack could not be started or driven (as opposed to a failed check)."""


class Api:
    """The engine's API."""

    def __init__(self, base: str, password: str = "", user: str = "viewer") -> None:
        self.base = base.rstrip("/")
        self.headers = {}
        if password:
            token = base64.b64encode(f"{user}:{password}".encode()).decode()
            self.headers["Authorization"] = f"Basic {token}"

    def get(self, path: str) -> Any:
        return self._send(urllib.request.Request(self.base + path, headers=self.headers))

    def broadcast(self, command: str, **fields: Any) -> Json:
        """Drives the simulator's broadcast."""
        return self._post("/api/broadcast", command, fields)

    def control(self, command: str, **fields: Any) -> Json:
        """Drives the viewer: the engine's DVR."""
        return self._post("/api/control", command, fields)

    def _post(self, path: str, command: str, fields: Json) -> Json:
        body = json.dumps({"schema_version": 1, "command": command, **fields}).encode()
        request = urllib.request.Request(
            self.base + path, body, {"Content-Type": "application/json", **self.headers}
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
    incidents: list[Json]
    seconds: float


def replay(api: Api, processes: list[Process], match: Json) -> Replay:
    """Broadcasts a match at full speed and returns what the engine made of it."""
    generation = api.get("/api/status")["generation"]
    api.broadcast("load_match", match_id=match["match_id"])
    api.broadcast("set_speed", speed=SPEED)
    api.broadcast("play")
    return until_ended(api, processes, match, generation)


def rewatch(api: Api, processes: list[Process], match: Json, target: Json) -> Replay:
    """Seeks the engine's viewer back to target and plays to the end at full speed."""
    generation = api.get("/api/status")["generation"]
    api.control("set_speed", speed=SPEED)
    api.control("seek", seek_to=target)
    return until_ended(api, processes, match, generation)


def until_ended(api: Api, processes: list[Process], match: Json, generation: int) -> Replay:
    """Waits for the engine to end match in a generation after generation."""
    match_id = match["match_id"]
    started = time.monotonic()
    while True:
        for p in processes:
            p.check_running()
        status: Json = api.get("/api/status")
        # Loading or seeking back starts a new generation; until then the status is the
        # previous one's.
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
        match,
        status,
        api.get("/api/metrics"),
        api.get("/api/alerts"),
        api.get("/api/incidents"),
        time.monotonic() - started,
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


def general_checks(r: Replay, allow_late: int = 0) -> list[str]:
    """What should hold for any match. Up to allow_late events may be dropped as
    too late: a feed in the provider's own order has a few (see --allow-late)."""
    problems = []
    match_id = r.match["match_id"]
    teams = {r.match["home_team"]["id"], r.match["away_team"]["id"]}

    seen = {t["id"] for t in r.status.get("teams", [])}
    if seen != teams:
        problems.append(f"the engine saw teams {sorted(seen)}, not {sorted(teams)}")
    if r.status["late_dropped"] > allow_late:
        problems.append(f"late_dropped is {r.status['late_dropped']}, more than {allow_late}")
    for counter in ("duplicates", "buffered"):
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
    score = {s["team_id"]: (s["goals"], s.get("shootout")) for s in r.status.get("score", [])}
    if score != {ARGENTINA: (3, 4), FRANCE: (3, 2)}:
        problems.append(f"the final score is {score}, not 3-3 and 4-2 on penalties")
    kinds = Counter(i["kind"] for i in r.incidents)
    expected = {"goal": 3, "penalty_goal": 3, "penalty_awarded": 3, "yellow_card": 8}
    if any(kinds[k] != n for k, n in expected.items()):
        problems.append(f"the incidents are {dict(kinds)}, not {expected} and the shootout")

    first_half = [s for s in r.metrics if s["window_s"] == 600 and s["period"] == 1]
    tilts = [t["field_tilt"] for s in first_half for t in s["teams"] if t["team_id"] == ARGENTINA]
    tilt = mean(tilts) if tilts else 0.0
    if tilt <= 0.5:
        problems.append(f"Argentina's first-half 10' field tilt averaged {tilt:.0%}, not over 50%")

    # Alerts should warn before a team scores, not after: Argentina were on top for the
    # few minutes before Messi's extra-time goal. (With the tuned thresholds, about
    # 2 alerts a rule a match, nothing warns of France's penalty at 79:24.)
    since, goal = clock(3, 97, 58), clock(4, 107, 58)
    if not any(a["team_id"] == ARGENTINA and since < when(a) < goal for a in r.alerts):
        problems.append(f"no alert for Argentina in the 10' before their goal at {at(goal)}")
    return problems


EXPECTATIONS: dict[int, Callable[[Replay], list[str]]] = {FINAL: final_checks}

REWATCH_FROM = {"period": 2, "match_clock_s": 3600}


def rewatch_checks(live: Replay, again: Replay) -> list[str]:
    """Rewatching rebuilds the match from the DVR's copy: exactly as it was built live."""
    problems = []
    if again.status["state"] != "ended" or again.status.get("behind_live_s") != 0:
        problems.append(f"after rewatching, the viewer is not live at the end: {again.status}")
    for what, before, after in (
        ("snapshots", live.metrics, again.metrics),
        ("alerts", live.alerts, again.alerts),
        ("incidents", live.incidents, again.incidents),
    ):
        if after != before:
            first = next(
                (i for i, (b, a) in enumerate(zip(before, after, strict=False)) if b != a), None
            )
            where = f", first at {at(after[first])}" if first is not None else ""
            problems.append(
                f"rewatching built {len(after)} {what}, not the {len(before)} built live{where}"
            )
    for counter in ("released", "late_dropped", "duplicates"):
        if again.status[counter] != live.status[counter]:
            problems.append(
                f"rewatching: {counter} is {again.status[counter]}, not {live.status[counter]}"
            )
    return problems


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


def check(
    api: Api,
    processes: list[Process],
    match: Json,
    alerts: list[Json],
    *,
    rewatching: bool,
    allow_late: int = 0,
) -> bool:
    """Replays a match (and rewatches it) and prints how it went. Adds the alerts the
    engine raised to alerts. Returns whether all checks passed."""
    match_id = match["match_id"]
    name = f"{match['home_team']['name']} v {match['away_team']['name']} ({match_id})"
    r = replay(api, processes, match)
    alerts.extend(r.alerts)
    expected = EXPECTATIONS[match_id](r) if match_id in EXPECTATIONS else []
    problems = general_checks(r, allow_late) + expected + log_errors(processes)
    print(
        f"{'✗' if problems else '✓'} {name}: ended after {r.seconds:.1f}s,"
        f" {len(r.metrics)} snapshots, {len(r.alerts)} alerts",
        flush=True,
    )
    report(problems)
    if not rewatching:
        return not problems

    again = rewatch(api, processes, match, REWATCH_FROM)
    alerts.extend(again.alerts)
    rewatch_problems = rewatch_checks(r, again) + log_errors(processes)
    print(
        f"{'✗' if rewatch_problems else '✓'} {name}: rewatched from {at(when(REWATCH_FROM))}"
        f" in {again.seconds:.1f}s",
        flush=True,
    )
    report(rewatch_problems)
    return not (problems or rewatch_problems)


def received(webhook: str) -> list[Json]:
    alerts: list[Json] = Api(webhook).get("/alerts")
    return alerts


def delivery_checks(webhook: str, before: int, raised: list[Json]) -> list[str]:
    """Waits for the notifier to deliver the alerts raised, and checks it delivered each
    once, as raised. Alerts the webhook had received before the run (its first `before`)
    are ignored."""
    expected = {a["id"]: a for a in raised}
    started = time.monotonic()
    while True:
        delivered = received(webhook)[before:]
        missing = expected.keys() - {a["id"] for a in delivered}
        if not missing or time.monotonic() - started > DELIVERY_TIMEOUT_S:
            break
        time.sleep(0.5)
    problems = [f"alert {i} was not delivered" for i in sorted(missing)]
    seen: set[str] = set()
    for a in delivered:
        if a["id"] in seen:
            problems.append(f"alert {a['id']} was delivered more than once")
        elif a["id"] not in expected:
            problems.append(f"alert {a['id']} was delivered but not raised in this run")
        elif a != expected[a["id"]]:
            problems.append(f"alert {a['id']} was delivered as {a}, raised as {expected[a['id']]}")
        seen.add(a["id"])
    return problems


def report(problems: list[str]) -> None:
    for problem in problems:
        print(f"    {problem}")


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
    parser.add_argument(
        "--webhook",
        metavar="URL",
        help="with --external, check the notifier delivered the alerts to this webhook_echo.py",
    )
    parser.add_argument(
        "--allow-late",
        type=int,
        default=0,
        metavar="N",
        help="pass with up to N events dropped as too late in a match. With jitter (as the"
        " smoke tests run the simulator) there are none; without it, the feed comes in"
        " StatsBomb's own order, which puts a few events far out of place (2 in the final:"
        " kick-off ball receipts indexed after the rest of their half)",
    )
    args = parser.parse_args()
    if args.webhook and not args.external:
        parser.error("--webhook needs --external")

    logs = Path(tempfile.mkdtemp(prefix="smoke-"))
    failed = True
    try:
        running: AbstractContextManager[list[Process]] = (
            nullcontext([]) if args.external else stack(args.sim_port, args.engine_port, logs)
        )
        with running as processes:
            api = Api(
                args.external or f"http://127.0.0.1:{args.engine_port}",
                os.environ.get("SMOKE_PASSWORD", ""),
                os.environ.get("SMOKE_USER", "viewer"),
            )
            downloaded = {m["match_id"]: m for m in wait_ready(api, processes)}
            before = len(received(args.webhook)) if args.webhook else 0
            raised: list[Json] = []
            # One pair of processes for every match, so switching matches is tested too.
            passed = [
                check(api, processes, m, raised, rewatching=i == 0, allow_late=args.allow_late)
                for i, m in enumerate(choose(args, downloaded))
            ]
            if len(passed) > 1:
                print(f"{sum(passed)} of {len(passed)} matches passed")
            failed = not all(passed)
            if args.webhook:
                problems = delivery_checks(args.webhook, before, raised)
                n = len({a["id"] for a in raised})
                print(f"{'✗' if problems else '✓'} the notifier delivered {n} alerts once each")
                report(problems)
                failed = failed or bool(problems)
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
