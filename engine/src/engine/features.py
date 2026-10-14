"""Model features: what the engine knows about each team at a tick.

The goal model is trained offline on these features (see model/) and served by
the engine from the same code, so what it learnt from is exactly what it sees
live. Every feature is computed from events the engine has already released:
nothing about the future, and nothing a live provider couldn't send.

For each team at each tick, from that team's point of view (`opp_` for its
opponent's):

- game state: minutes played, extra time, the score, minutes since the last goal;
- over the last 5 and 10 minutes: field tilt, xT added, the pressure index and
  some of its components, shots and xG;
- over the match so far: xG, shots, xT added and field tilt, a rough measure of
  which team is stronger on the day.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from engine.metrics import field_tilt, pressure, xt_added
from engine.metrics.field_tilt import is_attacking_third_touch
from engine.metrics.xt import xt_of_move
from engine.schema.event_schema import EventType, MatchEvent, ShotOutcome
from engine.ticks import SHOOTOUT_PERIOD, Tick

WINDOWS_MIN = (5, 10)
SIDES = ("", "opp_")
WINDOW_STATS = ("xt", "pressure", "shots", "xg", "box_entries", "box_actions", "recoveries")
MATCH_STATS = ("xg", "shots", "xt")
MAX_SINCE_GOAL_MIN = 45.0
EXTRA_TIME_PERIOD = 3

FEATURE_NAMES: tuple[str, ...] = (
    "minute",
    "extra_time",
    "score_diff",
    "goals_for",
    "goals_against",
    "since_goal_min",
    *(
        name
        for w in WINDOWS_MIN
        for name in (
            f"tilt_{w}",
            *(f"{side}{stat}_{w}" for stat in WINDOW_STATS for side in SIDES),
        )
    ),
    *(f"{side}{stat}_match" for stat in MATCH_STATS for side in SIDES),
    "tilt_match",
)


def goal_for(event: MatchEvent, team_ids: tuple[int, int] | None) -> int | None:
    """The team a goal counts for, if the event is one. An own goal's team is
    the side that conceded it. Shootout kicks are not goals."""
    if event.period == SHOOTOUT_PERIOD:
        return None
    if event.type == EventType.shot and event.shot and event.shot.outcome == ShotOutcome.goal:
        return event.team.id
    if event.type == EventType.own_goal and team_ids:
        a, b = team_ids
        return b if event.team.id == a else a
    return None


@dataclass
class _Totals:
    """One team's running totals over the match so far."""

    goals: int = 0
    xg: float = 0.0
    shots: int = 0
    xt: float = 0.0
    final_third_touches: int = 0


@dataclass
class FeatureTracker:
    """Computes the features at each tick, keeping the match's running totals.

    Give it every tick of a match, in order, as the detectors get them: the
    totals are built from the events each tick adds. It starts over for a new
    match, and when the pipeline does (a seek or a restarted match).
    """

    _match: tuple[int, int] | None = None
    """(match id, pipeline generation) of the ticks so far."""
    _seen: set[str] = field(default_factory=set)
    _totals: dict[int, _Totals] = field(default_factory=dict)
    _last_goal_s: float = 0.0

    def reset(self) -> None:
        self._seen = set()
        self._totals = {}
        self._last_goal_s = 0.0

    def observe(self, tick: Tick) -> dict[int, list[float]]:
        """Each team's features (in FEATURE_NAMES order) as of tick."""
        match = (tick.windows.match_id, tick.generation)
        if match != self._match:
            self._match = match
            self.reset()
        self._add(tick)
        windows = {w: _window(tick, w * 60.0) for w in WINDOWS_MIN}
        a, b = tick.team_ids
        return {a: self._features(tick, a, b, windows), b: self._features(tick, b, a, windows)}

    def _add(self, tick: Tick) -> None:
        """Count the events released since the last tick into the totals."""
        for team_id in tick.team_ids:
            self._totals.setdefault(team_id, _Totals())
        longest = max(tick.windows.lengths_s)
        for item in tick.windows.events(longest):
            e = item.event
            if e.id in self._seen:
                continue
            self._seen.add(e.id)
            if (scorer := goal_for(e, tick.team_ids)) is not None:
                self._totals[scorer].goals += 1
                self._last_goal_s = max(self._last_goal_s, item.play_s)
            totals = self._totals.get(e.team.id)
            if totals is None:
                continue
            if e.type is EventType.shot and e.shot is not None:
                totals.shots += 1
                totals.xg += e.shot.xg
            if (xt := xt_of_move(e, tick.metrics.grid)) is not None:
                totals.xt += xt
            if is_attacking_third_touch(e):
                totals.final_third_touches += 1

    def _features(
        self, tick: Tick, team: int, opp: int, windows: dict[int, dict[int, dict[str, float]]]
    ) -> list[float]:
        mine, theirs = self._totals[team], self._totals[opp]
        touches = mine.final_third_touches + theirs.final_third_touches
        values: dict[str, float] = {
            "minute": tick.play_s / 60.0,
            "extra_time": float(tick.item.event.period >= EXTRA_TIME_PERIOD),
            "score_diff": float(mine.goals - theirs.goals),
            "goals_for": float(mine.goals),
            "goals_against": float(theirs.goals),
            "since_goal_min": min((tick.play_s - self._last_goal_s) / 60.0, MAX_SINCE_GOAL_MIN),
            "xg_match": mine.xg,
            "opp_xg_match": theirs.xg,
            "shots_match": float(mine.shots),
            "opp_shots_match": float(theirs.shots),
            "xt_match": mine.xt,
            "opp_xt_match": theirs.xt,
            "tilt_match": mine.final_third_touches / touches if touches else 0.5,
        }
        for w, stats in windows.items():
            values[f"tilt_{w}"] = stats[team]["tilt"]
            for stat in WINDOW_STATS:
                values[f"{stat}_{w}"] = stats[team][stat]
                values[f"opp_{stat}_{w}"] = stats[opp][stat]
        return [values[name] for name in FEATURE_NAMES]


def _window(tick: Tick, length_s: float) -> dict[int, dict[str, float]]:
    """Each team's window stats over the last length_s of play."""
    events = tick.events(length_s)
    tilt = field_tilt(events, tick.team_ids)
    xt = xt_added(events, tick.team_ids, tick.metrics.grid)
    press = pressure(events, tick.team_ids)
    shots = _shots(events)
    return {
        t: {
            "tilt": tilt[t],
            "xt": xt[t],
            "pressure": press[t].index(tick.metrics.weights),
            "shots": float(shots.get(t, (0, 0.0))[0]),
            "xg": shots.get(t, (0, 0.0))[1],
            "box_entries": float(press[t].box_entries),
            "box_actions": float(press[t].box_actions),
            "recoveries": float(press[t].recoveries),
        }
        for t in tick.team_ids
    }


def _shots(events: Iterable[MatchEvent]) -> dict[int, tuple[int, float]]:
    """Each team's (shots, xG) in events."""
    totals: dict[int, tuple[int, float]] = {}
    for e in events:
        if e.type is EventType.shot and e.shot is not None:
            n, xg = totals.get(e.team.id, (0, 0.0))
            totals[e.team.id] = (n + 1, xg + e.shot.xg)
    return totals
