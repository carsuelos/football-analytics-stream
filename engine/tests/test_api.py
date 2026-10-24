import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing, asynccontextmanager
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from engine.api import NO_SIMULATOR, create_app
from engine.cli import server
from engine.dvr import InvalidCommandError, NoMatchError
from engine.hub import MatchHub
from engine.schema.engine_status_schema import EngineStatus
from engine.schema.viewer_command_schema import ViewerCommand
from tests.factories import alert, incident
from tests.test_hub import reset, snap, status, take
from tests.test_schema_contract import FIXTURES_DIR, _validator

BROADCAST = json.loads((FIXTURES_DIR / "valid/broadcast_status/playing.json").read_text())
MATCHES = json.loads((FIXTURES_DIR / "valid/match_list/one_match.json").read_text())
LIBRARY = json.loads((FIXTURES_DIR / "valid/match_library/downloading.json").read_text())
PLAY = {"schema_version": 1, "command": "play"}


def dump(m: BaseModel) -> Any:
    return m.model_dump(mode="json", exclude_none=True)


class FakeSimulator:
    """Answers every request with reply, and records the requests."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.reply: tuple[int, Any] | Exception = (200, BROADCAST)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.reply, Exception):
            raise self.reply
        code, body = self.reply
        if isinstance(body, bytes):
            return httpx.Response(code, content=body)
        return httpx.Response(code, json=body)


@pytest.fixture
def sim() -> FakeSimulator:
    return FakeSimulator()


class FakeControl:
    """Records viewer commands, and answers with status or raises error."""

    def __init__(self) -> None:
        self.commands: list[ViewerCommand] = []
        self.error: Exception | None = None

    def __call__(self, cmd: ViewerCommand) -> EngineStatus:
        self.commands.append(cmd)
        if self.error:
            raise self.error
        return status(7)


@pytest.fixture
def ctl() -> FakeControl:
    return FakeControl()


@pytest.fixture
def hub() -> MatchHub:
    return MatchHub()


@pytest.fixture
async def app(hub: MatchHub, sim: FakeSimulator, ctl: FakeControl) -> AsyncIterator[FastAPI]:
    transport = httpx.MockTransport(sim.handle)
    async with httpx.AsyncClient(transport=transport, base_url="http://simulator") as simulator:
        yield create_app(hub, simulator, control=ctl)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    # ASGITransport calls the app directly, with no server, but waits for the
    # whole response: fine for everything except the stream (see serving).
    transport = httpx.ASGITransport(app)
    async with httpx.AsyncClient(transport=transport, base_url="http://engine") as c:
        yield c


async def test_status_is_unavailable_until_the_engine_has_one(
    client: httpx.AsyncClient, hub: MatchHub
) -> None:
    r = await client.get("/api/status")
    assert (r.status_code, r.json()) == (503, {"error": "engine is starting"})
    hub.start(1, 1)
    hub.set_status(status(5))
    r = await client.get("/api/status")
    assert (r.status_code, r.json()) == (200, dump(status(5)))  # no nulls


async def test_metrics_alerts_and_incidents_are_the_match_so_far(
    client: httpx.AsyncClient, hub: MatchHub
) -> None:
    hub.start(1, 1)
    hub.add(snap(1), alert(1), incident(1), snap(2))
    assert (await client.get("/api/metrics")).json() == [dump(snap(1)), dump(snap(2))]
    assert (await client.get("/api/alerts")).json() == [dump(alert(1))]
    assert (await client.get("/api/incidents")).json() == [dump(incident(1))]
    hub.start(2, 1)
    assert (await client.get("/api/metrics")).json() == []
    assert (await client.get("/api/alerts")).json() == []
    assert (await client.get("/api/incidents")).json() == []


@pytest.mark.parametrize(
    ("path", "simulator_path", "reply"),
    [
        ("/api/matches", "/matches", MATCHES),
        ("/api/broadcast", "/status", BROADCAST),
        ("/api/library", "/library", LIBRARY),
    ],
)
async def test_gets_pass_through_to_the_simulator(
    client: httpx.AsyncClient, sim: FakeSimulator, path: str, simulator_path: str, reply: Any
) -> None:
    sim.reply = (200, reply)
    r = await client.get(path)
    assert (r.status_code, r.json()) == (200, reply)
    [req] = sim.requests
    assert (req.method, req.url.path) == ("GET", simulator_path)


async def test_a_download_passes_through_to_the_simulator(
    client: httpx.AsyncClient, sim: FakeSimulator
) -> None:
    sim.reply = (202, LIBRARY)
    command = {"schema_version": 1, "competition_id": 53, "season_id": 315}
    r = await client.post("/api/library", json=command)
    assert (r.status_code, r.json()) == (202, LIBRARY)
    [req] = sim.requests
    assert (req.method, req.url.path, json.loads(req.content)) == ("POST", "/library", command)
    sim.reply = (409, {"error": "a download is already running"})
    r = await client.post("/api/library", json=command)
    assert (r.status_code, r.json()) == (409, {"error": "a download is already running"})
    r = await client.post("/api/library", json={"schema_version": 1, "competition_id": 53})
    assert r.status_code == 400


@pytest.mark.parametrize(
    "command",
    [
        PLAY,
        {"schema_version": 1, "command": "load_match", "match_id": 3869685},
        {"schema_version": 1, "command": "set_speed", "speed": 60},
    ],
)
async def test_broadcast_commands_pass_through_and_return_the_broadcast_status(
    client: httpx.AsyncClient, sim: FakeSimulator, command: dict[str, Any]
) -> None:
    r = await client.post("/api/broadcast", json=command)
    assert (r.status_code, r.json()) == (200, BROADCAST)
    [req] = sim.requests
    assert (req.method, req.url.path) == ("POST", "/control")
    assert req.headers["content-type"] == "application/json"
    assert json.loads(req.content) == command


@pytest.mark.parametrize("path", ["/api/broadcast", "/api/control"])
async def test_an_invalid_command_goes_nowhere(
    client: httpx.AsyncClient, sim: FakeSimulator, ctl: FakeControl, path: str
) -> None:
    r = await client.post(path, json={"schema_version": 1, "command": "dance"})
    assert r.status_code == 400
    assert r.json()["error"].startswith("invalid request: command: Input should be ")
    r = await client.post(path, content=b"not json")
    assert r.status_code == 400
    assert r.json()["error"].startswith("invalid request: ")
    assert sim.requests == []
    assert ctl.commands == []


async def test_seek_is_a_viewer_command_not_a_broadcast_one(
    client: httpx.AsyncClient, sim: FakeSimulator
) -> None:
    seek = {"schema_version": 1, "command": "seek", "seek_to": {"period": 2, "match_clock_s": 60}}
    r = await client.post("/api/broadcast", json=seek)
    assert r.status_code == 400
    assert sim.requests == []


@pytest.mark.parametrize(
    "command",
    [
        PLAY,
        {"schema_version": 1, "command": "seek", "seek_to": {"period": 2, "match_clock_s": 4800}},
        {"schema_version": 1, "command": "go_live"},
    ],
)
async def test_viewer_commands_go_to_the_dvr_and_return_the_engine_status(
    client: httpx.AsyncClient, sim: FakeSimulator, ctl: FakeControl, command: dict[str, Any]
) -> None:
    r = await client.post("/api/control", json=command)
    assert (r.status_code, r.json()) == (200, dump(status(7)))
    assert [dump(c) for c in ctl.commands] == [command]
    assert sim.requests == []


@pytest.mark.parametrize(
    ("error", "code"),
    [(InvalidCommandError("speed too high"), 400), (NoMatchError("no match has started"), 409)],
)
async def test_viewer_command_errors(
    client: httpx.AsyncClient, ctl: FakeControl, error: Exception, code: int
) -> None:
    ctl.error = error
    r = await client.post("/api/control", json=PLAY)
    assert (r.status_code, r.json()) == (code, {"error": str(error)})


@pytest.mark.parametrize(
    ("simulator_code", "code"),
    [(400, 400), (404, 404), (409, 409), (500, 502), (503, 502)],
)
async def test_simulator_errors_pass_through_and_its_failures_are_bad_gateway(
    client: httpx.AsyncClient, sim: FakeSimulator, simulator_code: int, code: int
) -> None:
    sim.reply = (simulator_code, {"error": "no match loaded"})
    r = await client.post("/api/broadcast", json=PLAY)
    assert (r.status_code, r.json()) == (code, {"error": "no match loaded"})


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("connection refused"), httpx.ReadTimeout("timed out")],
)
async def test_an_unreachable_simulator_is_bad_gateway(
    client: httpx.AsyncClient, sim: FakeSimulator, failure: Exception
) -> None:
    sim.reply = failure
    r = await client.get("/api/broadcast")
    assert (r.status_code, r.json()) == (502, {"error": "simulator unavailable"})


@pytest.mark.parametrize(
    "reply",
    [
        (200, {"schema_version": 1, "state": "dancing", "speed": 1}),
        (200, b"not json"),
        (404, b"404 page not found\n"),  # Go's reply for a path it doesn't serve
    ],
)
async def test_an_invalid_reply_from_the_simulator_is_bad_gateway(
    client: httpx.AsyncClient, sim: FakeSimulator, reply: tuple[int, Any]
) -> None:
    sim.reply = reply
    r = await client.get("/api/broadcast")
    assert (r.status_code, r.json()) == (502, {"error": "invalid reply from simulator"})


@pytest.mark.parametrize(("method", "path"), [("GET", "/api/matches"), ("GET", "/api/broadcast")])
async def test_without_a_simulator_the_broadcast_endpoints_are_not_found(
    hub: MatchHub, ctl: FakeControl, method: str, path: str
) -> None:
    app = create_app(hub, None, control=ctl)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://e") as c:
        r = await c.request(method, path)
        assert (r.status_code, r.json()) == (404, {"error": NO_SIMULATOR})
        r = await c.post("/api/broadcast", json=PLAY)
        assert (r.status_code, r.json()) == (404, {"error": NO_SIMULATOR})
        # The viewer's controls don't need one.
        assert (await c.post("/api/control", json=PLAY)).status_code == 200


async def test_unknown_paths_and_methods_get_the_same_error_shape(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/api/nope")
    assert (r.status_code, r.json()) == (404, {"error": "Not Found"})
    r = await client.get("/api/control")
    assert (r.status_code, r.json()) == (405, {"error": "Method Not Allowed"})
    assert r.headers["allow"] == "POST"


@asynccontextmanager
async def serving(srv: uvicorn.Server) -> AsyncIterator[str]:
    """Run srv over real HTTP (give it port 0 for a free one), and yield its URL.

    The stream never ends, so it needs a real server: one that sends each event
    as it happens, and notices when the client goes away.
    """
    task = asyncio.create_task(srv.serve())
    try:
        async with asyncio.timeout(5):
            while not srv.started:
                if task.done():
                    await task  # it failed to start: raise why
                    raise RuntimeError("server exited before starting")
                await asyncio.sleep(0.01)
        host, port = srv.servers[0].sockets[0].getsockname()[:2]
        yield f"http://{host}:{port}"
    finally:
        srv.should_exit = True
        async with asyncio.timeout(5):  # fail, rather than hang, if it won't stop
            await task


def local(app: FastAPI, hub: MatchHub) -> uvicorn.Server:
    return server(app, hub, "127.0.0.1", 0)


async def sse(r: httpx.Response) -> AsyncGenerator[tuple[str, Any]]:
    """(event name, parsed data) for each event in a stream, skipping pings."""
    fields: dict[str, str] = {}
    async for line in r.aiter_lines():
        if line:
            if not line.startswith(":"):
                name, _, value = line.partition(": ")
                fields[name] = value
        elif fields:
            yield fields["event"], json.loads(fields["data"])
            fields = {}


SCHEMA_KINDS = {
    "reset": "match_reset",
    "status": "engine_status",
    "snapshot": "metric",
    "alert": "alert",
    "incident": "incident",
}


async def test_stream_sends_the_match_so_far_then_each_update(app: FastAPI, hub: MatchHub) -> None:
    hub.start(1, 1)
    hub.set_status(status(3))
    hub.add(snap(1), alert(1), incident(1))
    async with (
        serving(local(app, hub)) as url,
        httpx.AsyncClient(base_url=url) as client,
        client.stream("GET", "/api/stream") as r,
        aclosing(sse(r)) as events,
    ):
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        backlog = await take(events, 5)
        assert backlog == [
            ("reset", dump(reset(1))),
            ("status", dump(status(3))),
            ("snapshot", dump(snap(1))),
            ("alert", dump(alert(1))),
            ("incident", dump(incident(1))),
        ]
        hub.add(snap(2))
        hub.start(2, 1)
        live = await take(events, 2)
        assert live == [("snapshot", dump(snap(2))), ("reset", dump(reset(2)))]
    for name, data in backlog + live:
        _validator(SCHEMA_KINDS[name]).validate(data)


async def test_a_client_that_leaves_is_unsubscribed(app: FastAPI, hub: MatchHub) -> None:
    async with serving(local(app, hub)) as url, httpx.AsyncClient(base_url=url) as client:
        async with client.stream("GET", "/api/stream") as r:
            await take(aiter(sse(r)), 1)
            assert hub.subscribers == 1
        async with asyncio.timeout(1):
            while hub.subscribers:
                await asyncio.sleep(0.01)


async def test_the_stream_ends_when_the_client_falls_too_far_behind(
    app: FastAPI, hub: MatchHub
) -> None:
    hub.max_pending = 2
    async with (
        serving(local(app, hub)) as url,
        httpx.AsyncClient(base_url=url) as client,
        client.stream("GET", "/api/stream") as r,
        aclosing(sse(r)) as events,
    ):
        await take(events, 1)
        hub.add(snap(1), snap(2), snap(3))  # all at once: the third doesn't fit
        async with asyncio.timeout(1):
            assert [e async for e in events] == []
    assert hub.subscribers == 0


def test_the_api_is_documented(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    assert sorted(paths) == [
        "/api/alerts", "/api/broadcast", "/api/control", "/api/incidents", "/api/library",
        "/api/matches", "/api/metrics", "/api/status", "/api/stream",
    ]  # fmt: skip
    broadcast = paths["/api/broadcast"]["post"]
    assert broadcast["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/BroadcastCommand"
    }
    assert "502" in broadcast["responses"]
    control = paths["/api/control"]["post"]
    assert control["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ViewerCommand"
    }
    assert {"400", "409"} <= set(control["responses"])
    assert "text/event-stream" in paths["/api/stream"]["get"]["responses"]["200"]["content"]
