import asyncio
import logging
from types import TracebackType
from typing import Self

import httpx

from engine.schema.alert_schema import Alert

log = logging.getLogger(__name__)


class WebhookSink:
    """POSTs each alert as JSON to a URL, from a background worker.

    `send` only puts the alert on a bounded queue, so a slow or unreachable
    webhook never holds up the match; if the queue is full, the alert is
    dropped with a warning. The worker retries server errors and network
    failures with exponential backoff, then gives up on that alert.

    Use it as an async context manager: entering starts the worker, leaving
    delivers what is still queued, for up to drain_s, then stops.
    """

    def __init__(
        self,
        url: str,
        *,
        timeout_s: float = 5.0,
        retries: int = 3,
        backoff_s: float = 1.0,
        max_queued: int = 100,
        drain_s: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = url
        self.retries = retries
        self.backoff_s = backoff_s
        self.drain_s = drain_s
        self._queue: asyncio.Queue[Alert] = asyncio.Queue(max_queued)
        self._client = httpx.AsyncClient(timeout=timeout_s, transport=transport)
        self._worker: asyncio.Task[None] | None = None
        self._pending = 0
        """Alerts queued or being delivered."""

    async def __aenter__(self) -> Self:
        self._worker = asyncio.create_task(self._deliver_all())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # get() keeps returning what is queued, then raises QueueShutDown.
        self._queue.shutdown()
        if self._worker is not None:
            _, running = await asyncio.wait([self._worker], timeout=self.drain_s)
            if running:
                log.warning("webhook: stopping with %d alerts undelivered", self._pending)
                self._worker.cancel()
                await asyncio.wait([self._worker])
        await self._client.aclose()

    def send(self, alert: Alert) -> None:
        try:
            self._queue.put_nowait(alert)
        except asyncio.QueueFull:
            log.warning("webhook: queue full, dropped alert %s", alert.id)
        except asyncio.QueueShutDown:
            log.warning("webhook: stopped, dropped alert %s", alert.id)
        else:
            self._pending += 1

    async def _deliver_all(self) -> None:
        while True:
            try:
                alert = await self._queue.get()
            except asyncio.QueueShutDown:
                return
            try:
                await self._deliver(alert)
            finally:
                self._pending -= 1

    async def _deliver(self, alert: Alert) -> None:
        body = alert.model_dump_json()
        headers = {"content-type": "application/json"}
        for attempt in range(self.retries + 1):
            try:
                response = await self._client.post(self.url, content=body, headers=headers)
                response.raise_for_status()
                return
            except httpx.HTTPError as e:
                error = e
            if not _worth_retrying(error) or attempt == self.retries:
                break
            await asyncio.sleep(self.backoff_s * 2**attempt)
        log.warning("webhook: gave up on alert %s: %s", alert.id, error)


def _worth_retrying(error: httpx.HTTPError) -> bool:
    """Network failures, timeouts, server errors and rate limiting may pass;
    any other client error (a wrong URL, a rejected body) will not."""
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        return status >= 500 or status == httpx.codes.TOO_MANY_REQUESTS
    return isinstance(error, httpx.TransportError)
