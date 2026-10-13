"""A DVR over the broadcast: pause, rewind and replay the match being followed.

The broadcast only moves forward. The DVR sits between the event source and the
pipeline and keeps every message of the current match in memory (a match is a
few MB), so the viewer can pause, seek anywhere up to the live edge and play
back at their own speed without asking the source for anything again. That
works the same whatever the source: the simulator, a broker or a push-only
data provider.

The pipeline always gets the match in feed order, exactly as it was received,
so whatever it rebuilds after a seek is what it had live:

  - seeking back starts the pipeline over with a match_start, then replays
    everything before the target at once;
  - seeking forward or going live skips ahead at once, after a match_start
    that resumes where the pipeline is.

Either way the match_start's head marks the replayed events, so no alerts are
sent for them. Past the target, events are released at the viewer's speed in
match time, with the breaks between periods skipped, like the simulator's
broadcast. A viewer playing faster than the broadcast catches up and goes live.
"""

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import AsyncGenerator
from enum import StrEnum

from engine.clock import MatchClock, MatchTime
from engine.schema.engine_status_schema import LiveEdge
from engine.schema.event_schema import MatchEvent
from engine.schema.feed_schema import FeedMarker, FeedMessage
from engine.schema.feed_schema import FeedMessageKind as K
from engine.schema.viewer_command_schema import ViewerCommand
from engine.schema.viewer_command_schema import ViewerCommandType as C
from engine.sources import EventSource

log = logging.getLogger(__name__)

MAX_SPEED = 1000.0
KICK_OFF = MatchTime(1, 0.0)
_EPSILON_S = 1e-6


class Mode(StrEnum):
    live = "live"
    """Following the broadcast as it arrives."""
    playing = "playing"
    """Behind live, at the viewer's speed."""
    paused = "paused"


class NoMatchError(Exception):
    """The command needs a match, and none has started."""


class InvalidCommandError(ValueError):
    pass


class _Edge:
    """How far a stream of events in feed order has reached in match time.

    Feed order is only roughly match-time order, so earlier events are ignored.
    """

    def __init__(self) -> None:
        self._clock = MatchClock()

    def see(self, event: MatchEvent) -> None:
        if self._clock.now is None or MatchTime.of(event) >= self._clock.now:
            self._clock.advance(event)

    @property
    def now(self) -> MatchTime:
        return self._clock.now or KICK_OFF

    @property
    def started(self) -> bool:
        return self._clock.now is not None

    @property
    def play_s(self) -> float:
        return self._clock.play_s


class Dvr:
    """An EventSource that wraps another one and lets the viewer control it.

    Subscribe once; send commands with execute, from the same event loop.
    """

    def __init__(self, source: EventSource, *, speed: float = 1.0) -> None:
        self._source = source
        self.speed = speed
        """The viewer's playback speed while behind live."""
        self.mode = Mode.live
        self.match_id: int | None = None
        self._log: list[FeedMessage] = []
        """Every message of the match after its match_start, in feed order."""
        self._cursor = 0
        """Index in _log of the next message to release."""
        self._pending: deque[FeedMessage] = deque()
        """Messages to release before the log: match_starts, ours or the source's."""
        self._fast_until = 0
        """Index in _log: messages before it are a replay, released at once."""
        self._base = 0
        """Offset of the match's first message."""
        self._received_next = self._released_next = 0
        self._live = _Edge()
        self._viewer = _Edge()
        self._pos = KICK_OFF
        """While playing or paused: the viewer's position at wall time _anchor."""
        self._anchor = 0.0
        self._changed = asyncio.Event()

    async def subscribe(self, from_offset: int = 0) -> AsyncGenerator[FeedMessage]:
        reader = asyncio.create_task(self._read(from_offset))
        try:
            while True:
                self._changed.clear()
                step = self._step(_time())
                if isinstance(step, FeedMessage):
                    yield step
                    continue
                if reader.done():
                    reader.result()  # raise its error, if any
                    if not self._pending and self._cursor == len(self._log):
                        return
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._changed.wait(), step)
        finally:
            reader.cancel()
            await asyncio.wait([reader])

    def execute(self, cmd: ViewerCommand) -> None:
        """Apply a viewer command.

        Raises InvalidCommandError if it is malformed, and NoMatchError if it
        needs a match and none has started. set_speed doesn't need one.
        """
        t = _time()
        if cmd.command is C.set_speed:
            if cmd.speed is None or not 0 < cmd.speed <= MAX_SPEED:
                raise InvalidCommandError(f"set_speed requires 0 < speed <= {MAX_SPEED:g}")
            self._pos, self._anchor = self._now(t), t
            self.speed = cmd.speed
        elif cmd.command is C.seek and cmd.seek_to is None:
            raise InvalidCommandError("seek requires seek_to")
        elif self.match_id is None:
            raise NoMatchError("no match has started")
        else:
            match cmd.command:
                case C.play:
                    if self.mode is Mode.paused:
                        self.mode, self._anchor = Mode.playing, t
                case C.pause:
                    self._pos, self.mode = self._now(t), Mode.paused
                case C.seek:
                    assert cmd.seek_to is not None
                    self._seek(MatchTime(cmd.seek_to.period, cmd.seek_to.match_clock_s), t)
                case C.go_live:
                    self._go_live()
        log.info("viewer %s: %s, %s", cmd.command, self.mode, self._now(t))
        self._changed.set()

    def live_edge(self) -> LiveEdge | None:
        """The latest point of the broadcast received so far."""
        if self.match_id is None:
            return None
        now = self._live.now
        return LiveEdge(
            offset=self._received_next,
            period=now.period,
            match_clock_s=now.clock_s,
            play_s=self._live.play_s,
        )

    def behind_live_s(self) -> float | None:
        """Seconds of play between the viewer and the live edge."""
        if self.match_id is None:
            return None
        viewer = self._viewer.play_s
        if self.mode is not Mode.live and self._viewer.started:
            pos, last = self._now(_time()), self._viewer.now
            if pos.period == last.period and pos.clock_s > last.clock_s:
                viewer += pos.clock_s - last.clock_s
        return max(0.0, self._live.play_s - viewer)

    # --- the source side ---

    async def _read(self, from_offset: int) -> None:
        try:
            async for msg in self._source.subscribe(from_offset):
                self._receive(msg)
                self._changed.set()
        finally:
            self._changed.set()

    def _receive(self, msg: FeedMessage) -> None:
        match msg.kind:
            case K.match_start:
                start = _marker(msg)
                if start.match_id == self.match_id and start.offset == self._received_next:
                    self._log.append(msg)  # a reconnect, resuming where we were
                else:
                    self._new_match(start, msg)
            case K.event:
                if msg.event is None:
                    raise ValueError("event message without an event")
                self._log.append(msg)
                self._received_next = max(self._received_next, msg.event.offset + 1)
                self._live.see(msg.event)
            case K.match_end:
                self._log.append(msg)

    def _new_match(self, start: FeedMarker, msg: FeedMessage) -> None:
        log.info("match %d: following live from offset %d", start.match_id, start.offset)
        self.match_id = start.match_id
        self.mode = Mode.live
        self._log.clear()
        self._cursor = self._fast_until = 0
        self._pending = deque([msg])
        self._base = self._received_next = self._released_next = start.offset
        self._live, self._viewer = _Edge(), _Edge()
        self._pos = KICK_OFF

    # --- the pipeline side ---

    def _step(self, t: float) -> FeedMessage | float | None:
        """The next message to release now; or else how long to wait for it,
        or None to wait for a command or more of the broadcast."""
        if self._pending:
            return self._pending.popleft()
        while self._cursor < len(self._log):
            msg = self._log[self._cursor]
            fast = self._cursor < self._fast_until
            if msg.kind is K.match_start:
                # The source's resume after a reconnect: its head marks what was
                # missed meanwhile. Only meaningful when live; we resume ourselves.
                self._cursor += 1
                if self.mode is Mode.live and not fast:
                    return msg
                continue
            if not fast and self.mode is Mode.paused:
                return None
            if not fast and self.mode is Mode.playing and msg.event is not None:
                wait = self._until_due(msg.event, t)
                if wait > 0:
                    return wait
            self._cursor += 1
            if fast and self._cursor == self._fast_until:
                self._anchor = t  # play on from the target once rebuilt
            if msg.event is not None:
                self._released_next = max(self._released_next, msg.event.offset + 1)
                self._viewer.see(msg.event)
            return msg
        if self.mode is Mode.playing:
            log.info("match %s: caught up with the broadcast", self.match_id)
            self.mode = Mode.live
        return None

    def _until_due(self, event: MatchEvent, t: float) -> float:
        """Seconds until event is due at the viewer's speed; 0 if it is due now."""
        cur, at = self._now(t), MatchTime.of(event)
        if at.period > cur.period:
            # Feed order: the current period is over. Skip the break.
            self._pos, self._anchor = at, t
            return 0
        if at.period == cur.period and at.clock_s > cur.clock_s + _EPSILON_S:
            return (at.clock_s - cur.clock_s) / self.speed
        return 0

    def _now(self, t: float) -> MatchTime:
        """The viewer's position at wall time t."""
        match self.mode:
            case Mode.live:
                return self._viewer.now
            case Mode.paused:
                return self._pos
            case Mode.playing:
                return MatchTime(
                    self._pos.period, self._pos.clock_s + (t - self._anchor) * self.speed
                )

    def _seek(self, target: MatchTime, t: float) -> None:
        if target >= self._live.now:
            self._go_live()
            return
        assert self.match_id is not None
        # The first message the viewer hasn't seen at target. One exists: the
        # live edge is an event past target.
        k = next(i for i, m in enumerate(self._log) if m.event and MatchTime.of(m.event) > target)
        head = max((m.event.offset + 1 for m in self._log[:k] if m.event), default=self._base)
        if k < self._cursor:
            # Back: start the pipeline over and replay up to the target.
            self._pending.clear()
            self._pending.append(_start(self.match_id, self._base, head, KICK_OFF))
            self._cursor = 0
            self._released_next = self._base
            self._viewer = _Edge()
        else:
            # Forward: resume where the pipeline is and catch up to the target.
            self._pending.append(_start(self.match_id, self._released_next, head, self._viewer.now))
        self._fast_until = k
        # Clamped to the period's first event, so play starts right away.
        period_start = min(
            (
                MatchTime.of(m.event)
                for m in self._log
                if m.event and m.event.period == target.period
            ),
            default=target,
        )
        self._pos, self._anchor = max(target, period_start), t
        if self.mode is not Mode.paused:
            self.mode = Mode.playing

    def _go_live(self) -> None:
        assert self.match_id is not None
        if self._cursor < len(self._log):
            self._pending.append(
                _start(self.match_id, self._released_next, self._received_next, self._viewer.now)
            )
            self._fast_until = len(self._log)
        self.mode = Mode.live


def _time() -> float:
    return asyncio.get_running_loop().time()


def _start(match_id: int, offset: int, head: int, at: MatchTime) -> FeedMessage:
    marker = FeedMarker(
        match_id=match_id, offset=offset, period=at.period, match_clock_s=at.clock_s, head=head
    )
    return FeedMessage(schema_version=1, kind=K.match_start, marker=marker)


def _marker(msg: FeedMessage) -> FeedMarker:
    if msg.marker is None:
        raise ValueError(f"{msg.kind} message without a marker")
    return msg.marker
