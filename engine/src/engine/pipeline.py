"""From feed messages to ordered, windowed events."""

import logging

from engine.clock import MatchClock, ReorderBuffer, TimedEvent
from engine.schema.common_schema import Team
from engine.schema.event_schema import MatchEvent
from engine.schema.feed_schema import FeedMarker, FeedMessage, FeedMessageKind
from engine.windows import (
    FIVE_MINUTES_S,
    TEN_MINUTES_S,
    SlidingWindows,
    StateStore,
    WindowMode,
)

log = logging.getLogger(__name__)


class Pipeline:
    """Feed messages in; events in match-time order, placed in windows, out.

        feed message -> ReorderBuffer -> MatchClock -> SlidingWindows

    One match at a time. match_start and reset both start from scratch:
    match_start because a match is (re)loaded, reset because the feed is about
    to replay the match from offset 0 after a seek. A match_start for the
    current match at exactly the next expected offset is a reconnect instead,
    and keeps the state built so far.

    Replayed events rebuild the windows; `is_replay` tells later stages
    (alerts) not to act on them. They are the events before a seek's target
    and, after a match_start, the catch-up on everything already published
    when we (re)connected: acting on those would raise stale alerts.
    """

    def __init__(
        self,
        store: StateStore,
        *,
        allowed_lateness_s: float = 5.0,
        window_mode: WindowMode = WindowMode.CONTINUOUS,
        window_lengths_s: tuple[float, ...] = (FIVE_MINUTES_S, TEN_MINUTES_S),
    ) -> None:
        self.store = store
        self.window_mode = window_mode
        self.window_lengths_s = window_lengths_s
        self.buffer = ReorderBuffer(allowed_lateness_s)
        self.clock = MatchClock()
        self.windows: SlidingWindows | None = None
        self.ended = False
        """True once match_end has been seen, until the next start or reset."""
        self.replay_end_offset = 0
        """Events below this offset happened before we were live: a replay after
        a seek, or a catch-up after (re)connecting."""
        self.teams: dict[int, Team] = {}
        """Teams seen in this match, in order of first appearance."""
        self.generation = 0
        """Goes up each time the pipeline starts over, so later stages that keep
        their own state (detectors) know to start over too."""
        self._next_offset = 0

    @property
    def match_id(self) -> int | None:
        return self.windows.match_id if self.windows else None

    @property
    def team_ids(self) -> tuple[int, int] | None:
        """The match's two team ids, once both have appeared in the feed."""
        if len(self.teams) < 2:
            return None
        a, b, *_ = self.teams
        return a, b

    @property
    def rebuilding(self) -> bool:
        """True while the feed is replaying or catching up (see replay_end_offset)."""
        return self._next_offset < self.replay_end_offset

    def is_replay(self, item: TimedEvent) -> bool:
        return item.event.offset < self.replay_end_offset

    def handle(self, msg: FeedMessage) -> list[TimedEvent]:
        """Process one feed message; return the events it released, in order."""
        match msg.kind:
            case FeedMessageKind.match_start:
                marker = _marker(msg)
                if marker.match_id == self.match_id and marker.offset == self._next_offset:
                    log.info("match %d: resumed at offset %d", marker.match_id, marker.offset)
                else:
                    log.info("match %d: start at offset %d", marker.match_id, marker.offset)
                    self._start(marker.match_id)
                if marker.head is not None:
                    # Everything published before we connected, and nothing more.
                    self.replay_end_offset = marker.head
                if self.rebuilding:
                    log.info("match %d: catching up to offset %d", marker.match_id, marker.head)
                return []
            case FeedMessageKind.reset:
                marker = _marker(msg)
                log.info(
                    "match %d: seek, rebuilding up to offset %d", marker.match_id, marker.offset
                )
                self._start(marker.match_id)
                self.replay_end_offset = marker.offset
                return []
            case FeedMessageKind.event:
                if msg.event is None:
                    raise ValueError("event message without an event")
                return self._place(self.buffer.push(self._check(msg.event)))
            case FeedMessageKind.match_end:
                log.info("match %d: end at offset %d", _marker(msg).match_id, _marker(msg).offset)
                self.ended = True
                return self._place(self.buffer.flush())

    def _start(self, match_id: int) -> None:
        if self.windows:
            self.windows.reset()
        self.windows = SlidingWindows(
            self.store, match_id, lengths_s=self.window_lengths_s, mode=self.window_mode
        )
        self.windows.reset()
        self.buffer.reset()
        self.clock.reset()
        self.ended = False
        self.replay_end_offset = 0
        self.teams = {}
        self.generation += 1
        self._next_offset = 0

    def _check(self, event: MatchEvent) -> MatchEvent:
        if self.match_id is None:
            raise ValueError(f"event {event.id} arrived before match_start")
        if event.match_id != self.match_id:
            raise ValueError(f"event {event.id} is for match {event.match_id}, not {self.match_id}")
        self._next_offset = max(self._next_offset, event.offset + 1)
        return event

    def _place(self, events: list[MatchEvent]) -> list[TimedEvent]:
        assert self.windows is not None
        placed = []
        for event in events:
            item = self.clock.advance(event)
            self.teams.setdefault(event.team.id, event.team)
            self.windows.add(item)
            placed.append(item)
        return placed


def _marker(msg: FeedMessage) -> FeedMarker:
    if msg.marker is None:
        raise ValueError(f"{msg.kind} message without a marker")
    return msg.marker
