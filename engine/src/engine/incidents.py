"""Incidents: the match's key moments (goals, cards, penalties) and the score.

The score is kept here, from the events, rather than taken from the provider:
a goal counts when its shot or own goal is released, and stops counting if a
goal_disallowed event later cancels it (as a real feed does after a VAR
review). Penalty shootout kicks have their own count and are not goals.
"""

import logging

from engine.clock import TimedEvent
from engine.pipeline import Pipeline
from engine.schema.common_schema import TeamScore
from engine.schema.event_schema import Card, EventType, MatchEvent, ShotOutcome, ShotType
from engine.schema.incident_schema import Incident, IncidentKind
from engine.ticks import SHOOTOUT_PERIOD

log = logging.getLogger(__name__)

CARD_KINDS = {
    Card.yellow: IncidentKind.yellow_card,
    Card.second_yellow: IncidentKind.second_yellow,
    Card.red: IncidentKind.red_card,
}


class IncidentTracker:
    """Picks the incidents out of the events a pipeline releases, and keeps the score.

    Give it every event the pipeline releases, in order, replays included, so
    the score after a seek is what it was live. It starts over when the
    pipeline does.
    """

    def __init__(self) -> None:
        self._generation = -1
        self.reset()

    def reset(self) -> None:
        self._goals: dict[int, int] = {}
        self._shootout: dict[int, int] | None = None
        self._counted: dict[str, Incident] = {}
        """Goals that count, by the id of the event that scored them."""
        self._awarded: set[int] = set()
        """Teams awarded a penalty they have not taken yet: a provider may flag
        both the foul and the foul won, and that is one penalty."""

    def score(self, pipeline: Pipeline) -> list[TeamScore] | None:
        """The score, in the pipeline's order of teams, once both have appeared."""
        if pipeline.team_ids is None:
            return None
        if pipeline.generation != self._generation:
            self._sync(pipeline)
        return [
            TeamScore(
                team_id=team_id,
                goals=self._goals.get(team_id, 0),
                shootout=None if self._shootout is None else self._shootout.get(team_id, 0),
            )
            for team_id in pipeline.team_ids
        ]

    def observe(self, pipeline: Pipeline, item: TimedEvent) -> list[Incident]:
        """Take one event released by pipeline; return the incidents it is."""
        self._sync(pipeline)
        e = item.event
        found: list[tuple[IncidentKind, int, MatchEvent, dict[str, object]]] = []

        def add(kind: IncidentKind, team_id: int, **extra: object) -> None:
            found.append((kind, team_id, e, extra))

        other = _other(pipeline, e.team.id)
        if e.type is EventType.shot and e.shot is not None:
            penalty = e.shot.type is ShotType.penalty
            scored = e.shot.outcome is ShotOutcome.goal
            if e.period == SHOOTOUT_PERIOD:
                if self._shootout is None:
                    self._shootout = {}
                if scored:
                    self._shootout[e.team.id] = self._shootout.get(e.team.id, 0) + 1
                add(IncidentKind.shootout_goal if scored else IncidentKind.shootout_miss, e.team.id)
            else:
                if penalty:
                    self._awarded.discard(e.team.id)
                if scored:
                    self._goals[e.team.id] = self._goals.get(e.team.id, 0) + 1
                    add(IncidentKind.penalty_goal if penalty else IncidentKind.goal, e.team.id)
                elif penalty:
                    add(IncidentKind.penalty_missed, e.team.id)
        elif e.type is EventType.own_goal and e.period != SHOOTOUT_PERIOD:
            if other is None:
                log.warning("own goal %s before both teams appeared: not counted", e.id)
            else:
                self._goals[other] = self._goals.get(other, 0) + 1
                add(IncidentKind.own_goal, other)
        elif e.type is EventType.goal_disallowed and e.disallowed_goal is not None:
            goal = self._counted.pop(e.disallowed_goal.event_id, None)
            if goal is None:
                log.warning("%s disallows goal %s, which is not one", e.id, e.disallowed_goal)
            else:
                self._goals[goal.team_id] -= 1
                add(
                    IncidentKind.goal_disallowed,
                    goal.team_id,
                    cancels=goal.id,
                    reason=e.disallowed_goal.reason,
                    player=goal.player,
                )

        if e.penalty_awarded and e.period != SHOOTOUT_PERIOD:
            to = other if e.type is EventType.foul_committed else e.team.id
            if to is not None and to not in self._awarded:
                self._awarded.add(to)
                # The player who gave it away, if this is the foul; omitted for the foul won.
                player = e.player if e.type is EventType.foul_committed else None
                add(IncidentKind.penalty_awarded, to, player=player)
        if e.card is not None:
            add(CARD_KINDS[e.card], e.team.id)

        score = self.score(pipeline)
        if found and score is None:
            log.warning("%s before both teams appeared: no incident", e.id)
            return []
        incidents = []
        for kind, team_id, event, extra in found:
            incident = Incident.model_validate(
                {
                    "schema_version": 1,
                    # The same incident gets the same id when the match is replayed.
                    "id": f"{event.match_id}-{event.id}-{kind}",
                    "match_id": event.match_id,
                    "offset": event.offset,
                    "period": event.period,
                    "match_clock_s": event.match_clock_s,
                    "play_s": item.play_s,
                    "kind": kind,
                    "team_id": team_id,
                    "player": event.player,
                    "score": score,
                    **extra,
                }
            )
            if kind in (IncidentKind.goal, IncidentKind.penalty_goal, IncidentKind.own_goal):
                self._counted[event.id] = incident
            incidents.append(incident)
        return incidents

    def _sync(self, pipeline: Pipeline) -> None:
        if pipeline.generation != self._generation:
            self._generation = pipeline.generation
            self.reset()


def _other(pipeline: Pipeline, team_id: int) -> int | None:
    if pipeline.team_ids is None:
        return None
    a, b = pipeline.team_ids
    return b if team_id == a else a
