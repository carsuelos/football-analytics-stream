import asyncio
from collections.abc import AsyncIterator, Callable

import pytest

from engine.detectors import Detectors
from engine.dvr import Dvr, InvalidCommandError, Mode, NoMatchError
from engine.hub import MatchHub
from engine.metrics import MetricsConfig, XTGrid
from engine.pipeline import Pipeline
from engine.runner import engine_status, run
from engine.schema.engine_status_schema import EngineState
from engine.schema.feed_schema import FeedMessage
from engine.schema.feed_schema import FeedMessageKind as K
from engine.schema.viewer_command_schema import SeekTarget, ViewerCommand, ViewerCommandType
from engine.ticks import Ticker
from engine.windows import InMemoryStateStore
from tests.factories import AWAY, HOME, event, feed_event, feed_marker
from tests.test_detectors import Fake

# These tests run in real time, at high playback speeds: 10 s of match time at
# speed 100 is 0.1 s. Timings are checked with a generous tolerance.

SPEED = 100.0
TOLERANCE_S = 0.05


class QueueSource:
    """An EventSource fed by the test; None ends it, an exception fails it."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[FeedMessage | Exception | None] = asyncio.Queue()
        self.from_offsets: list[int] = []

    def send(self, *msgs: FeedMessage | Exception | None) -> None:
        for msg in msgs:
            self.queue.put_nowait(msg)

    async def subscribe(self, from_offset: int = 0) -> AsyncIterator[FeedMessage]:
        self.from_offsets.append(from_offset)
        while True:
            msg = await self.queue.get()
            if msg is None:
                return
            if isinstance(msg, Exception):
                raise msg
            yield msg


class Viewer:
    """Reads a Dvr in the background, recording what it releases and when."""

    def __init__(self, dvr: Dvr) -> None:
        self.dvr = dvr
        self.got: list[tuple[str, float]] = []
        self.msgs: list[FeedMessage] = []
        self._loop = asyncio.get_running_loop()
        self._start = self._loop.time()
        self.task = asyncio.create_task(self._read())

    async def _read(self) -> None:
        async for msg in self.dvr.subscribe():
            self.msgs.append(msg)
            self.got.append((describe(msg), self._loop.time() - self._start))

    async def take(self, n: int, timeout_s: float = 2) -> list[str]:
        """Wait for n more messages and return them."""
        want = len(self.got) + n
        async with asyncio.timeout(timeout_s):
            while len(self.got) < want:
                if self.task.done():
                    await self.task
                    raise AssertionError(f"ended after {[d for d, _ in self.got]}")
                await asyncio.sleep(0.001)
        return [d for d, _ in self.got[want - n : want]]

    async def nothing(self, wait_s: float = 0.1) -> None:
        before = len(self.got)
        await asyncio.sleep(wait_s)
        assert [d for d, _ in self.got[before:]] == []

    def at(self, i: int) -> float:
        """When the i-th message was released, in seconds since the start."""
        return self.got[i][1]

    def since_start(self) -> float:
        return self._loop.time() - self._start


def describe(msg: FeedMessage) -> str:
    if msg.event:
        return f"event {msg.event.offset}"
    assert msg.marker is not None
    head = f" head {msg.marker.head}" if msg.marker.head is not None else ""
    return f"{msg.kind} {msg.marker.offset}{head}"


def cmd(
    command: ViewerCommandType,
    *,
    speed: float | None = None,
    to: tuple[int, float] | None = None,
) -> ViewerCommand:
    seek_to = SeekTarget(period=to[0], match_clock_s=to[1]) if to else None
    return ViewerCommand(schema_version=1, command=command, speed=speed, seek_to=seek_to)


PLAY = cmd(ViewerCommandType.play)
PAUSE = cmd(ViewerCommandType.pause)
GO_LIVE = cmd(ViewerCommandType.go_live)


def seek(period: int, clock_s: float) -> ViewerCommand:
    return cmd(ViewerCommandType.seek, to=(period, clock_s))


def speed(s: float) -> ViewerCommand:
    return cmd(ViewerCommandType.set_speed, speed=s)


def events(*at: tuple[int, float]) -> list[FeedMessage]:
    """Event messages at the given (period, clock)s, with offsets 0, 1, 2..."""
    teams = [HOME, AWAY]
    return [feed_event(event(p, c, offset=i, team=teams[i % 2])) for i, (p, c) in enumerate(at)]


START = feed_marker(K.match_start, 0, head=0)


async def started(*msgs: FeedMessage) -> tuple[QueueSource, Dvr, Viewer]:
    """A DVR at SPEED over a source that has sent the match start, then msgs,
    all already released live."""
    source = QueueSource()
    dvr = Dvr(source, speed=SPEED)
    viewer = Viewer(dvr)
    source.send(START, *msgs)
    await viewer.take(1 + len(msgs))
    return source, dvr, viewer


async def test_live_passes_the_source_through_unchanged() -> None:
    msgs = [START, *events((1, 0), (1, 10)), feed_marker(K.match_end, 2)]
    source = QueueSource()
    source.send(*msgs, None)
    got = [m async for m in Dvr(source).subscribe(5)]
    assert got == msgs
    assert source.from_offsets == [5]


async def test_pause_holds_the_broadcast_and_play_releases_it_in_match_time() -> None:
    source, dvr, viewer = await started(*events((1, 0)))
    dvr.execute(PAUSE)
    source.send(*events((1, 0), (1, 10), (1, 30))[1:])
    await viewer.nothing()
    assert dvr.mode is Mode.paused

    played = viewer.since_start()
    dvr.execute(PLAY)
    assert await viewer.take(2) == ["event 1", "event 2"]
    assert viewer.at(2) - played == pytest.approx(10 / SPEED, abs=TOLERANCE_S)
    assert viewer.at(3) - played == pytest.approx(30 / SPEED, abs=TOLERANCE_S)
    # Caught up with the broadcast: live again.
    await until(lambda: dvr.mode is Mode.live)


async def test_play_skips_the_break_between_periods() -> None:
    source, dvr, viewer = await started(*events((1, 0)))
    dvr.execute(PAUSE)
    source.send(*events((1, 0), (1, 20), (2, 2700), (2, 2710))[1:])
    await viewer.nothing(0.01)
    played = viewer.since_start()
    dvr.execute(PLAY)
    assert await viewer.take(3) == ["event 1", "event 2", "event 3"]
    assert viewer.at(2) - played == pytest.approx(20 / SPEED, abs=TOLERANCE_S)
    # The second half starts right after the first half's last event.
    assert viewer.at(3) - viewer.at(2) == pytest.approx(0, abs=TOLERANCE_S)
    assert viewer.at(4) - viewer.at(3) == pytest.approx(10 / SPEED, abs=TOLERANCE_S)


async def test_seeking_back_starts_over_and_replays_up_to_the_target_at_once() -> None:
    msgs = events((1, 0), (1, 10), (1, 20), (1, 30))
    _, dvr, viewer = await started(*msgs)
    dvr.execute(seek(1, 15))
    assert dvr.mode is Mode.playing
    # A match_start the pipeline can't take for a resume, and everything up to
    # 00:15 as a replay, at once.
    assert await viewer.take(3) == ["match_start 0 head 2", "event 0", "event 1"]
    replayed = viewer.at(len(viewer.got) - 1)
    assert await viewer.take(2) == ["event 2", "event 3"]
    assert viewer.at(len(viewer.got) - 2) - replayed == pytest.approx(5 / SPEED, abs=TOLERANCE_S)
    assert viewer.at(len(viewer.got) - 1) - replayed == pytest.approx(15 / SPEED, abs=TOLERANCE_S)


async def test_seeking_while_paused_rebuilds_and_stays_paused() -> None:
    _, dvr, viewer = await started(*events((1, 0), (1, 10), (1, 20)))
    dvr.execute(PAUSE)
    dvr.execute(seek(1, 10))
    assert await viewer.take(3) == ["match_start 0 head 2", "event 0", "event 1"]
    await viewer.nothing()
    assert dvr.mode is Mode.paused


async def test_seeking_forward_resumes_and_catches_up_to_the_target() -> None:
    _, dvr, viewer = await started(*events((1, 0), (1, 10), (1, 20), (1, 30)))
    dvr.execute(seek(1, 5))
    dvr.execute(PAUSE)
    await viewer.take(2)  # match_start, event 0
    dvr.execute(seek(1, 25))
    # A resume at our next offset; its head marks the skipped events as a replay.
    assert await viewer.take(3) == ["match_start 1 head 3", "event 1", "event 2"]
    await viewer.nothing()


async def test_seeking_to_the_start_of_a_period_plays_from_its_first_event() -> None:
    _, dvr, viewer = await started(*events((1, 0), (1, 10), (2, 2700), (2, 2710)))
    dvr.execute(seek(2, 0))  # 00:00 is before the second half's kick-off at 45:00
    assert await viewer.take(4) == ["match_start 0 head 2", "event 0", "event 1", "event 2"]
    n = len(viewer.got)
    assert viewer.at(n - 1) - viewer.at(n - 2) == pytest.approx(0, abs=TOLERANCE_S)


async def test_seeking_to_or_past_the_live_edge_goes_live() -> None:
    source, dvr, viewer = await started(*events((1, 0), (1, 10)))
    dvr.execute(PAUSE)
    source.send(*events((1, 0), (1, 10), (1, 20))[2:])
    await viewer.nothing(0.01)
    dvr.execute(seek(2, 0))
    assert dvr.mode is Mode.live
    assert await viewer.take(2) == ["match_start 2 head 3", "event 2"]


async def test_go_live_catches_up_at_once_and_follows_the_broadcast() -> None:
    source, dvr, viewer = await started(*events((1, 0)))
    dvr.execute(PAUSE)
    msgs = events((1, 0), (1, 100), (1, 200), (1, 300))
    source.send(*msgs[1:3])
    await viewer.nothing(0.01)
    dvr.execute(GO_LIVE)
    assert await viewer.take(3) == ["match_start 1 head 3", "event 1", "event 2"]
    source.send(msgs[3])
    assert await viewer.take(1) == ["event 3"]
    assert dvr.mode is Mode.live


async def test_go_live_when_live_does_nothing() -> None:
    _, dvr, viewer = await started(*events((1, 0)))
    dvr.execute(GO_LIVE)
    await viewer.nothing()


async def test_a_reconnect_is_passed_on_live_and_left_out_behind_live() -> None:
    source, dvr, viewer = await started(*events((1, 0)))
    msgs = events((1, 0), (1, 10), (1, 20))
    reconnect = feed_marker(K.match_start, 1, head=2)
    source.send(reconnect, msgs[1])
    assert await viewer.take(2) == ["match_start 1 head 2", "event 1"]

    # Behind live, the DVR resumes the pipeline itself.
    dvr.execute(seek(1, 5))
    source.send(feed_marker(K.match_start, 2, head=3), msgs[2])
    assert await viewer.take(4) == ["match_start 0 head 1", "event 0", "event 1", "event 2"]
    await viewer.nothing()


async def test_a_new_match_from_the_source_starts_over_live() -> None:
    source, dvr, viewer = await started(*events((1, 0), (1, 10)))
    dvr.execute(seek(1, 0))
    dvr.execute(PAUSE)
    await viewer.take(1)
    other = feed_event(event(1, 0, offset=0, match_id=2))
    source.send(feed_marker(K.match_start, 0, match_id=2, head=0), other)
    assert await viewer.take(2) == ["match_start 0 head 0", "event 0"]
    assert (dvr.mode, dvr.match_id) == (Mode.live, 2)
    assert dvr.speed == SPEED  # kept


async def test_the_same_match_reloaded_starts_over() -> None:
    source, dvr, viewer = await started(*events((1, 0), (1, 10)))
    source.send(START, *events((1, 0)))
    assert await viewer.take(2) == ["match_start 0 head 0", "event 0"]
    assert dvr.live_edge() is not None and dvr.live_edge().offset == 1  # type: ignore[union-attr]


async def test_set_speed_while_playing_counts_time_already_played_at_the_old_speed() -> None:
    source, dvr, viewer = await started(*events((1, 0)))
    dvr.execute(PAUSE)
    source.send(*events((1, 0), (1, 20))[1:])
    await viewer.nothing(0.01)
    dvr.execute(speed(10))
    played = viewer.since_start()
    dvr.execute(PLAY)
    await asyncio.sleep(0.5)  # 5 s of match time at 10x
    dvr.execute(speed(SPEED))  # the remaining 15 s at 100x
    await viewer.take(1)
    assert viewer.at(len(viewer.got) - 1) - played == pytest.approx(0.65, abs=TOLERANCE_S)


async def test_status_tracks_the_live_edge_and_how_far_behind_the_viewer_is() -> None:
    _, dvr, viewer = await started(*events((1, 0), (1, 60), (1, 50)))
    edge = dvr.live_edge()
    assert edge is not None
    assert (edge.offset, edge.period, edge.match_clock_s, edge.play_s) == (3, 1, 60, 60)
    assert dvr.behind_live_s() == 0
    dvr.execute(PAUSE)
    dvr.execute(seek(1, 30))
    await viewer.take(2)
    assert dvr.behind_live_s() == pytest.approx(30)  # paused at 00:30


async def test_status_is_empty_before_a_match() -> None:
    dvr = Dvr(QueueSource())
    assert (dvr.live_edge(), dvr.behind_live_s(), dvr.mode) == (None, None, Mode.live)


@pytest.mark.parametrize("command", [PLAY, PAUSE, seek(1, 0), GO_LIVE])
async def test_commands_need_a_match(command: ViewerCommand) -> None:
    with pytest.raises(NoMatchError):
        Dvr(QueueSource()).execute(command)


async def test_speed_can_be_set_before_a_match() -> None:
    dvr = Dvr(QueueSource())
    dvr.execute(speed(4))
    assert dvr.speed == 4


@pytest.mark.parametrize(
    "command",
    [
        cmd(ViewerCommandType.set_speed),
        ViewerCommand.model_construct(
            schema_version=1, command=ViewerCommandType.set_speed, speed=1001
        ),
        cmd(ViewerCommandType.seek),
    ],
)
async def test_invalid_commands(command: ViewerCommand) -> None:
    _, dvr, _ = await started()
    with pytest.raises(InvalidCommandError):
        dvr.execute(command)


async def test_a_source_failure_reaches_the_consumer() -> None:
    source = QueueSource()
    source.send(START, ConnectionError("boom"))
    with pytest.raises(ConnectionError):
        async for _ in Dvr(source).subscribe():
            pass


async def test_a_finished_source_ends_the_dvr_once_everything_is_released() -> None:
    source, dvr, viewer = await started(*events((1, 0)))
    dvr.execute(PAUSE)
    source.send(*events((1, 0), (1, 10))[1:], None)
    await viewer.nothing(0.01)
    assert not viewer.task.done()  # paused, with an event to go
    dvr.execute(PLAY)
    await viewer.take(1)
    async with asyncio.timeout(1):
        await viewer.task


# --- with the pipeline ---


def jittered_match() -> list[FeedMessage]:
    """Two halves of events, a few out of order, each team on the ball in turn."""
    at: list[tuple[int, float]] = []
    for period, kick_off in ((1, 0), (2, 2700)):
        for i in range(60):
            clock = kick_off + i * 50 + (30 if i % 7 == 3 else 0)  # some arrive late
            at.append((period, clock))
    return events(*at)


METRICS = MetricsConfig(XTGrid.from_lists([[0.01 * (x + 1)] * 12 for x in range(8)]))


async def follow(source: QueueSource, dvr: Dvr, p: Pipeline, hub: MatchHub) -> asyncio.Task[None]:
    return asyncio.create_task(
        run(
            dvr,
            p,
            ticker=Ticker(METRICS),
            detectors=Detectors([Fake()]),
            hub=hub,
            report=lambda _: None,
        )
    )


async def until(condition: Callable[[], object], timeout_s: float = 3) -> None:
    async with asyncio.timeout(timeout_s):
        while not condition():
            await asyncio.sleep(0.005)


def match_results(hub: MatchHub) -> tuple[list[object], list[object]]:
    return (
        [s.model_dump(exclude={"replay"}) for s in hub.snapshots],
        [a.model_dump(exclude={"replay"}) for a in hub.alerts],
    )


async def test_a_seek_back_and_replay_rebuilds_exactly_what_was_built_live() -> None:
    msgs = jittered_match()
    source = QueueSource()
    dvr = Dvr(source, speed=1000)
    p, hub = Pipeline(InMemoryStateStore(), allowed_lateness_s=40), MatchHub()
    task = await follow(source, dvr, p, hub)
    source.send(START, *msgs, feed_marker(K.match_end, len(msgs)))
    await until(lambda: p.ended)
    live = match_results(hub)
    assert live[1], "the test match should raise alerts"
    live_late = p.buffer.stats.late_dropped

    dvr.execute(seek(2, 5400))  # the last 4 minutes, to replay quickly
    await until(lambda: hub.generation == 2 and not p.rebuilding)
    before = [s for s in live[0] if (s["period"], s["match_clock_s"]) <= (2, 5400)]  # type: ignore[index]
    assert match_results(hub)[0] == before[: len(hub.snapshots)]
    await until(lambda: p.ended, timeout_s=5)
    assert match_results(hub) == live
    assert p.buffer.stats.late_dropped == live_late
    assert engine_status(p, dvr).state is EngineState.ended
    task.cancel()
    await asyncio.wait([task])


async def test_engine_status_shows_the_viewer() -> None:
    source = QueueSource()
    dvr = Dvr(source, speed=SPEED)
    p, hub = Pipeline(InMemoryStateStore(), allowed_lateness_s=0), MatchHub()
    assert engine_status(p, dvr).state is EngineState.waiting
    task = await follow(source, dvr, p, hub)
    source.send(START, *events((1, 0), (1, 60), (1, 120)))
    await until(lambda: p.buffer.stats.released == 3)
    s = engine_status(p, dvr)
    assert (s.state, s.speed, s.behind_live_s) == (EngineState.live, SPEED, 0)
    assert s.live_edge is not None and s.live_edge.offset == 3

    dvr.execute(PAUSE)
    assert engine_status(p, dvr).state is EngineState.paused
    dvr.execute(seek(1, 30))
    await until(lambda: p.generation == 2)
    s = engine_status(p, dvr)
    assert s.state is EngineState.paused
    assert s.behind_live_s == pytest.approx(90)
    dvr.execute(PLAY)
    assert engine_status(p, dvr).state is EngineState.playing
    await until(lambda: dvr.mode is Mode.live)
    assert engine_status(p, dvr).behind_live_s == 0
    task.cancel()
    await asyncio.wait([task])
