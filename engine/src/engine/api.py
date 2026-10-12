"""The HTTP API: the match stream for the dashboard, and playback passthrough.

GET  /api/stream    the match as server-sent events (see stream below)
GET  /api/status    where the engine is in the match
GET  /api/metrics   the match's metric snapshots so far
GET  /api/alerts    the match's alerts so far
GET  /api/matches   the simulator's matches
GET  /api/playback  the simulator's playback status
POST /api/control   send the simulator a playback command

Every error has the simulator's shape: {"error": "..."}.
"""

import logging
from collections.abc import AsyncIterable, Callable
from contextlib import AbstractAsyncContextManager, aclosing
from typing import Any, assert_never

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from engine.hub import MatchHub, Update
from engine.schema.alert_schema import Alert
from engine.schema.command_schema import PlaybackCommand
from engine.schema.engine_status_schema import EngineStatus
from engine.schema.match_list_schema import MatchList
from engine.schema.match_reset_schema import MatchReset
from engine.schema.metric_schema import MetricSnapshot
from engine.schema.status_schema import PlaybackStatus

log = logging.getLogger(__name__)


class ApiError(BaseModel):
    """The body of every error response, from the engine or the simulator."""

    error: str


SIMULATOR_ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": ApiError, "description": "The simulator rejected the request"},
    404: {"model": ApiError, "description": "No such match"},
    409: {"model": ApiError, "description": "No match is loaded"},
    502: {"model": ApiError, "description": "The simulator is down or failed"},
}


def event_name(update: Update) -> str:
    """The SSE event name for an update, for addEventListener in the browser."""
    match update:
        case MatchReset():
            return "reset"
        case EngineStatus():
            return "status"
        case MetricSnapshot():
            return "snapshot"
        case Alert():
            return "alert"
        case _:
            assert_never(update)


def create_app(
    hub: MatchHub,
    simulator: httpx.AsyncClient,
    *,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
) -> FastAPI:
    """The API over hub. simulator is a client whose base_url is the simulator's.

    lifespan, if given, runs around the app's life (e.g. the engine's run loop).
    """
    app = FastAPI(
        title="Football analytics engine",
        description="Live match metrics and alerts, and playback passthrough to the simulator.",
        lifespan=lifespan,
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, e: StarletteHTTPException) -> JSONResponse:
        return JSONResponse({"error": e.detail}, e.status_code, headers=e.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, e: RequestValidationError) -> JSONResponse:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'][1:]) or 'body'}: {err['msg']}"
            for err in e.errors()
        )
        return JSONResponse({"error": f"invalid request: {problems}"}, 400)

    @app.get("/api/stream", response_class=EventSourceResponse)
    async def stream() -> AsyncIterable[ServerSentEvent]:
        """The match as server-sent events, named reset, status, snapshot and alert.

        First the latest reset, status and the match so far, then each update as
        it happens. On a reset, start the match over. If the stream ends, the
        browser reconnects and gets the whole match again.
        """
        async with aclosing(hub.subscribe()) as updates:
            async for update in updates:
                yield ServerSentEvent(
                    event=event_name(update), raw_data=update.model_dump_json(exclude_none=True)
                )

    @app.get(
        "/api/status",
        response_model_exclude_none=True,
        responses={503: {"model": ApiError, "description": "The engine is starting"}},
    )
    async def status() -> EngineStatus:
        if hub.status is None:
            raise HTTPException(503, "engine is starting")
        return hub.status

    @app.get("/api/metrics", response_model_exclude_none=True)
    async def metrics() -> list[MetricSnapshot]:
        return hub.snapshots

    @app.get("/api/alerts", response_model_exclude_none=True)
    async def alerts() -> list[Alert]:
        return hub.alerts

    async def call_simulator[M: BaseModel](
        reply: type[M], method: str, path: str, body: BaseModel | None = None
    ) -> M:
        """Send the simulator a request, and parse a successful reply as the given model.

        Its 4xx errors pass through, since the request was at fault; anything
        else that goes wrong is a 502.
        """
        try:
            if body is None:
                r = await simulator.request(method, path)
            else:
                r = await simulator.request(
                    method,
                    path,
                    content=body.model_dump_json(exclude_none=True),
                    headers={"Content-Type": "application/json"},
                )
        except httpx.HTTPError as e:
            log.warning("simulator unavailable: %s %s: %r", method, path, e)
            raise HTTPException(502, "simulator unavailable") from e
        try:
            if r.is_success:
                return reply.model_validate_json(r.content)
            error = ApiError.model_validate_json(r.content).error
        except ValidationError as e:
            log.warning("invalid reply from simulator: %s %s: %s", method, path, e)
            raise HTTPException(502, "invalid reply from simulator") from e
        raise HTTPException(r.status_code if r.status_code < 500 else 502, error)

    @app.get("/api/matches", response_model_exclude_none=True, responses=SIMULATOR_ERRORS)
    async def matches() -> MatchList:
        return await call_simulator(MatchList, "GET", "/matches")

    @app.get("/api/playback", response_model_exclude_none=True, responses=SIMULATOR_ERRORS)
    async def playback() -> PlaybackStatus:
        return await call_simulator(PlaybackStatus, "GET", "/status")

    @app.post("/api/control", response_model_exclude_none=True, responses=SIMULATOR_ERRORS)
    async def control(command: PlaybackCommand) -> PlaybackStatus:
        return await call_simulator(PlaybackStatus, "POST", "/control", command)

    return app
