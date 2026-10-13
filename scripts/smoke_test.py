# /// script
# requires-python = ">=3.13"
# ///
"""End-to-end smoke test: replays matches through the simulator and engine, and checks the results.

    uv run scripts/smoke_test.py                    # the 2022 World Cup final
    uv run scripts/smoke_test.py --match 3857256    # another downloaded match

Builds and starts the simulator (delivering events up to 3s late, so the
engine has to reorder them) and the engine, on their own ports so a dev setup
can keep running. Each match is played at 1000x through the engine's
/api/control until the engine reports it ended, then its metrics and alerts
are checked. Needs `make fetch-data`, Go and uv. Exits 1 if a check fails, and
then keeps the processes' logs.
"""

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
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

    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}"

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


def at(x: Json) -> str:
    """Where something happened, e.g. "P2 82:27"."""
    m, s = divmod(int(x["match_clock_s"]), 60)
    return f"P{x['period']} {m}:{s:02}"


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
        offsets = [s["offset"] for s in m if s["window_s"] == window_s]
        if offsets != sorted(offsets):
            problems.append(f"{window_s}s snapshots are out of order")

    a = r.alerts
    report([x for x in a if x["match_id"] != match_id], "alerts are for another match")
    report([x for x in a if x["team_id"] not in teams], "alerts are for another team")
    report([x for x in a if x["value"] < x["threshold"]], "alerts are below their threshold")
    if len({x["id"] for x in a}) != len(a):
        problems.append("alert ids are not unique")
    return problems


def log_errors(processes: list[Process]) -> list[str]:
    """Errors the processes logged, though they kept running."""
    errors = []
    for p in processes:
        for line in p.log.read_text(errors="replace").splitlines():
            if "ERROR" in line or "Traceback" in line or "panic:" in line:
                errors.append(f"{p.name}: {line.strip()}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--match", type=int, default=FINAL, help="match id (default: the final)")
    parser.add_argument("--sim-port", type=int, default=18080)
    parser.add_argument("--engine-port", type=int, default=18000)
    args = parser.parse_args()

    logs = Path(tempfile.mkdtemp(prefix="smoke-"))
    failed = True
    try:
        with stack(args.sim_port, args.engine_port, logs) as processes:
            api = Api(args.engine_port)
            matches = {m["match_id"]: m for m in wait_ready(api, processes)}
            if args.match not in matches:
                raise SmokeError(f"match {args.match} is not downloaded (see make fetch-data)")

            match = matches[args.match]
            name = f"{match['home_team']['name']} v {match['away_team']['name']} ({args.match})"
            r = replay(api, processes, match)
            problems = general_checks(r) + log_errors(processes)
            print(
                f"{'✗' if problems else '✓'} {name}: ended after {r.seconds:.1f}s,"
                f" {len(r.metrics)} snapshots, {len(r.alerts)} alerts"
            )
            for problem in problems:
                print(f"    {problem}")
            failed = bool(problems)
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
