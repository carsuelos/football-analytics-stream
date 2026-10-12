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

from engine.api import create_app
from engine.hub import MatchHub
from tests.factories import alert
from tests.test_hub import reset, snap, status, take
from tests.test_schema_contract import FIXTURES_DIR, _validator

PLAYBACK = json.loads((FIXTURES_DIR / "valid/status/playing.json").read_text())
MATCHES = json.loads((FIXTURES_DIR / "valid/match_list/one_match.json").read_text())
PLAY = {"schema_version": 1, "command": "play"}


def dump(m: BaseModel) -> Any:
    return m.model_dump(mode="json", exclude_none=True)


class FakeSimulator:
    """Answers every request with reply, and records the requests."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.reply: tuple[int, Any] | Exception = (200, PLAYBACK)

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


@pytest.fixture
def hub() -> MatchHub:
    return MatchHub()


@pytest.fixture
async def app(hub: MatchHub, sim: FakeSimulator) -> AsyncIterator[FastAPI]:
    transport = httpx.MockTransport(sim.handle)
    async with httpx.AsyncClient(transport=transport, base_url="http://simulator") as simulator:
        yield create_app(hub, simulator)


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


async def test_metrics_and_alerts_are_the_match_so_far(
    client: httpx.AsyncClient, hub: MatchHub
) -> None:
    hub.start(1, 1)
    hub.add(snap(1), alert(1), snap(2))
    assert (await client.get("/api/metrics")).json() == [dump(snap(1)), dump(snap(2))]
    assert (await client.get("/api/alerts")).json() == [dump(alert(1))]
    hub.start(2, 1)
    assert (await client.get("/api/metrics")).json() == []
    assert (await client.get("/api/alerts")).json() == []


@pytest.mark.parametrize(
    ("path", "simulator_path", "reply"),
    [("/api/matches", "/matches", MATCHES), ("/api/playback", "/status", PLAYBACK)],
)
async def test_gets_pass_through_to_the_simulator(
    client: httpx.AsyncClient, sim: FakeSimulator, path: str, simulator_path: str, reply: Any
) -> None:
    sim.reply = (200, reply)
    r = await client.get(path)
    assert (r.status_code, r.json()) == (200, reply)
    [req] = sim.requests
    assert (req.method, req.url.path) == ("GET", simulator_path)


@pytest.mark.parametrize(
    "command",
    [
        PLAY,
        {"schema_version": 1, "command": "load_match", "match_id": 3869685},
        {"schema_version": 1, "command": "seek", "seek_to": {"period": 2, "match_clock_s": 4800}},
    ],
)
async def test_control_passes_the_command_through_and_returns_the_playback_status(
    client: httpx.AsyncClient, sim: FakeSimulator, command: dict[str, Any]
) -> None:
    r = await client.post("/api/control", json=command)
    assert (r.status_code, r.json()) == (200, PLAYBACK)
    [req] = sim.requests
    assert (req.method, req.url.path) == ("POST", "/control")
    assert req.headers["content-type"] == "application/json"
    assert json.loads(req.content) == command


async def test_an_invalid_command_never_reaches_the_simulator(
    client: httpx.AsyncClient, sim: FakeSimulator
) -> None:
    r = await client.post("/api/control", json={"schema_version": 1, "command": "dance"})
    assert r.status_code == 400
    assert r.json()["error"].startswith("invalid request: command: Input should be 'load_match'")
    r = await client.post("/api/control", content=b"not json")
    assert r.status_code == 400
    assert r.json()["error"].startswith("invalid request: ")
    assert sim.requests == []


@pytest.mark.parametrize(
    ("simulator_code", "code"),
    [(400, 400), (404, 404), (409, 409), (500, 502), (503, 502)],
)
async def test_simulator_errors_pass_through_and_its_failures_are_bad_gateway(
    client: httpx.AsyncClient, sim: FakeSimulator, simulator_code: int, code: int
) -> None:
    sim.reply = (simulator_code, {"error": "no match loaded"})
    r = await client.post("/api/control", json=PLAY)
    assert (r.status_code, r.json()) == (code, {"error": "no match loaded"})


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("connection refused"), httpx.ReadTimeout("timed out")],
)
async def test_an_unreachable_simulator_is_bad_gateway(
    client: httpx.AsyncClient, sim: FakeSimulator, failure: Exception
) -> None:
    sim.reply = failure
    r = await client.get("/api/playback")
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
    r = await client.get("/api/playback")
    assert (r.status_code, r.json()) == (502, {"error": "invalid reply from simulator"})


async def test_unknown_paths_and_methods_get_the_same_error_shape(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/api/nope")
    assert (r.status_code, r.json()) == (404, {"error": "Not Found"})
    r = await client.get("/api/control")
    assert (r.status_code, r.json()) == (405, {"error": "Method Not Allowed"})
    assert r.headers["allow"] == "POST"


@asynccontextmanager
async def serving(app: FastAPI) -> AsyncIterator[str]:
    """Serve app over real HTTP on a free local port, and yield its URL.

    The stream never ends, so it needs a real server: one that sends each event
    as it happens, and notices when the client goes away.
    """
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, lifespan="off", log_level="warning",
        timeout_graceful_shutdown=1,
    )  # fmt: skip
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(5):
            while not server.started:
                await asyncio.sleep(0.01)
        host, port = server.servers[0].sockets[0].getsockname()[:2]
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        await task


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
}


async def test_stream_sends_the_match_so_far_then_each_update(app: FastAPI, hub: MatchHub) -> None:
    hub.start(1, 1)
    hub.set_status(status(3))
    hub.add(snap(1), alert(1))
    async with (
        serving(app) as url,
        httpx.AsyncClient(base_url=url) as client,
        client.stream("GET", "/api/stream") as r,
        aclosing(sse(r)) as events,
    ):
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        backlog = await take(events, 4)
        assert backlog == [
            ("reset", dump(reset(1))),
            ("status", dump(status(3))),
            ("snapshot", dump(snap(1))),
            ("alert", dump(alert(1))),
        ]
        hub.add(snap(2))
        hub.start(2, 1)
        live = await take(events, 2)
        assert live == [("snapshot", dump(snap(2))), ("reset", dump(reset(2)))]
    for name, data in backlog + live:
        _validator(SCHEMA_KINDS[name]).validate(data)


async def test_a_client_that_leaves_is_unsubscribed(app: FastAPI, hub: MatchHub) -> None:
    async with serving(app) as url, httpx.AsyncClient(base_url=url) as client:
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
        serving(app) as url,
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
        "/api/alerts", "/api/control", "/api/matches", "/api/metrics",
        "/api/playback", "/api/status", "/api/stream",
    ]  # fmt: skip
    control = paths["/api/control"]["post"]
    assert control["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PlaybackCommand"
    }
    assert "502" in control["responses"]
    assert "text/event-stream" in paths["/api/stream"]["get"]["responses"]["200"]["content"]
