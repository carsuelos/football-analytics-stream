import asyncio
import json
import logging
from collections.abc import Callable, Coroutine

import httpx
import pytest

from engine.sinks import LogSink, WebhookSink
from tests.factories import alert

URL = "http://hooks.test/alerts"
Handler = Callable[[httpx.Request], Coroutine[None, None, httpx.Response]]


class Hook:
    """A fake webhook that answers with the given statuses in turn (an
    exception is raised instead), then 200s, and records each body."""

    def __init__(self, *answers: int | Exception) -> None:
        self.answers = list(answers)
        self.bodies: list[dict[str, object]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        assert (request.method, str(request.url)) == ("POST", URL)
        assert request.headers["content-type"] == "application/json"
        self.bodies.append(json.loads(request.content))
        answer = self.answers.pop(0) if self.answers else 200
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer)

    def ids(self) -> list[object]:
        return [b["id"] for b in self.bodies]


def webhook(
    handler: Handler,
    *,
    retries: int = 3,
    backoff_s: float = 0,
    max_queued: int = 100,
    drain_s: float = 5.0,
) -> WebhookSink:
    return WebhookSink(
        URL,
        retries=retries,
        backoff_s=backoff_s,
        max_queued=max_queued,
        drain_s=drain_s,
        transport=httpx.MockTransport(handler),
    )


def test_log_sink_writes_one_line_per_alert(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        LogSink().send(alert())
    assert caplog.messages == ["ALERT P2 82:27 control_shift: France taking control"]


async def test_webhook_posts_each_alert_as_json_in_order() -> None:
    hook = Hook()
    async with webhook(hook) as sink:
        sink.send(alert(1))
        await asyncio.sleep(0.01)
        sink.send(alert(2))
    assert hook.bodies[0] == alert(1).model_dump(mode="json")
    assert hook.ids() == [alert(1).id, alert(2).id]


async def test_webhook_retries_failures_that_may_pass() -> None:
    refused = httpx.ConnectError("refused")
    hook = Hook(500, 429, refused, 200, 503)
    async with webhook(hook) as sink:
        sink.send(alert(1))
        sink.send(alert(2))
    assert hook.ids() == [alert(1).id] * 4 + [alert(2).id] * 2


async def test_webhook_gives_up_after_the_retries(caplog: pytest.LogCaptureFixture) -> None:
    hook = Hook(500, 500, 500)
    async with webhook(hook, retries=2) as sink:
        sink.send(alert(1))
        sink.send(alert(2))
    assert hook.ids() == [alert(1).id] * 3 + [alert(2).id]
    [message] = caplog.messages
    assert message.startswith(f"webhook: gave up on alert {alert(1).id}: Server error '500")


@pytest.mark.parametrize("status", [400, 404])
async def test_webhook_does_not_retry_other_client_errors(status: int) -> None:
    hook = Hook(status)
    async with webhook(hook) as sink:
        sink.send(alert(1))
    assert hook.ids() == [alert(1).id]


async def test_webhook_backs_off_exponentially(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    sleep = asyncio.sleep

    async def record(delay: float) -> None:
        sleeps.append(delay)
        await sleep(0)

    monkeypatch.setattr(asyncio, "sleep", record)
    async with webhook(Hook(500, 500, 500), backoff_s=0.5) as sink:
        sink.send(alert())
    assert sleeps == [0.5, 1.0, 2.0]


async def test_webhook_drops_alerts_when_the_queue_is_full(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hook = Hook()
    async with webhook(hook, max_queued=1) as sink:
        sink.send(alert(1))
        sink.send(alert(2))
    assert hook.ids() == [alert(1).id]
    assert caplog.messages == [f"webhook: queue full, dropped alert {alert(2).id}"]


async def test_webhook_stops_waiting_for_a_hung_hook(caplog: pytest.LogCaptureFixture) -> None:
    answered = 0

    async def hang_after_one(request: httpx.Request) -> httpx.Response:
        nonlocal answered
        if answered:
            await asyncio.sleep(60)
        answered += 1
        return httpx.Response(200)

    async with webhook(hang_after_one, drain_s=0.05) as sink:
        for n in range(3):
            sink.send(alert(n))
    assert answered == 1
    assert caplog.messages == ["webhook: stopping with 2 alerts undelivered"]
    assert [t for t in asyncio.all_tasks() if t is not asyncio.current_task()] == []


async def test_webhook_drops_alerts_sent_after_it_stopped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hook = Hook()
    async with webhook(hook) as sink:
        pass
    sink.send(alert())
    assert hook.bodies == []
    assert caplog.messages == [f"webhook: stopped, dropped alert {alert().id}"]
