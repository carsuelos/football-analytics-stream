from engine.backtest import Step, replay
from engine.features import FEATURE_NAMES, FeatureTracker, goal_for
from engine.metrics import MetricsConfig, XTGrid
from engine.pipeline import Pipeline
from engine.schema.common_schema import Team
from engine.schema.event_schema import EventOutcome, EventType, MatchEvent, ShotDetail, ShotOutcome
from engine.schema.feed_schema import FeedMessage
from engine.schema.feed_schema import FeedMessageKind as K
from tests.factories import AWAY, HOME, event, feed_event, feed_marker

# xT rises by 0.01 per column, so a pass forward one zone adds 0.01.
METRICS = MetricsConfig(XTGrid.from_lists([[c / 100 for c in range(12)]] * 8))
F = {name: i for i, name in enumerate(FEATURE_NAMES)}


def shot(clock_s: float, outcome: ShotOutcome, team: Team = HOME, period: int = 1) -> MatchEvent:
    return event(
        period,
        clock_s,
        type=EventType.shot,
        team=team,
        location=(110, 40),
        shot=ShotDetail(xg=0.25, outcome=outcome),
    )


def forward_pass(clock_s: float, team: Team) -> MatchEvent:
    return event(
        1,
        clock_s,
        team=team,
        location=(85, 40),
        end_location=(95, 40),
        outcome=EventOutcome.success,
    )


def feed(events: list[MatchEvent], match_id: int = 1) -> list[FeedMessage]:
    return [
        feed_marker(K.match_start, 0, head=0, match_id=match_id),
        *map(feed_event, events),
        feed_marker(K.match_end, len(events), match_id=match_id),
    ]


def a_match(extra: list[MatchEvent] | None = None) -> list[FeedMessage]:
    """Thirty minutes: HOME passing forward every 20s, AWAY every 60s, a HOME
    goal at 10', a saved AWAY shot at 12' and an AWAY own goal at 20'."""
    events = [forward_pass(float(s), HOME if s % 60 else AWAY) for s in range(0, 1800, 20)]
    events += [
        shot(600, ShotOutcome.goal),
        shot(720, ShotOutcome.saved, team=AWAY),
        event(1, 1200, type=EventType.own_goal, team=AWAY),  # counts for HOME
        *(extra or []),
    ]
    events.sort(key=lambda e: e.match_clock_s)
    return feed(events)


def features(messages: list[FeedMessage]) -> dict[float, dict[int, list[float]]]:
    """Each team's features at each tick, by play time."""
    tracker = FeatureTracker()
    seen: dict[float, dict[int, list[float]]] = {}

    def on_step(_: Pipeline, step: Step) -> None:
        if step.tick is not None:
            seen[step.tick.play_s] = tracker.observe(step.tick)

    replay(messages, METRICS, on_step=on_step)
    return seen


def test_feature_names_are_unique() -> None:
    assert len(set(FEATURE_NAMES)) == len(FEATURE_NAMES) == 43


def test_goal_for() -> None:
    teams = (HOME.id, AWAY.id)
    assert goal_for(shot(0, ShotOutcome.goal), teams) == HOME.id
    assert goal_for(shot(0, ShotOutcome.post), teams) is None
    assert goal_for(event(1, 0, type=EventType.own_goal, team=AWAY), teams) == HOME.id
    assert goal_for(shot(0, ShotOutcome.goal, period=5), teams) is None
    assert goal_for(event(1, 0), teams) is None


def test_game_state() -> None:
    seen = features(a_match())
    home, away = seen[900.0][HOME.id], seen[900.0][AWAY.id]
    assert home[F["minute"]] == 15
    assert (home[F["score_diff"]], home[F["goals_for"]], home[F["goals_against"]]) == (1, 1, 0)
    assert away[F["score_diff"]] == -1
    assert home[F["since_goal_min"]] == away[F["since_goal_min"]] == 5
    assert seen[1500.0][HOME.id][F["score_diff"]] == 2  # the own goal counts for HOME
    assert seen[1500.0][HOME.id][F["since_goal_min"]] == 5
    assert seen[300.0][HOME.id][F["since_goal_min"]] == 5  # since kick-off
    assert home[F["extra_time"]] == 0


def test_windows_and_totals() -> None:
    at = features(a_match())[840.0]
    home, away = at[HOME.id], at[AWAY.id]
    # The last 5' is (540, 840]: HOME's goal, AWAY's saved shot, 10 HOME and 5 AWAY passes.
    assert (home[F["shots_5"]], home[F["xg_5"]], home[F["opp_shots_5"]]) == (1, 0.25, 1)
    assert (away[F["shots_5"]], away[F["opp_xg_5"]]) == (1, 0.25)
    assert home[F["shots_10"]] == 1
    assert round(home[F["xt_5"]], 6) == 0.1
    assert round(home[F["opp_xt_5"]], 6) == round(away[F["xt_5"]], 6) == 0.05
    assert home[F["tilt_5"]] + away[F["tilt_5"]] == 1
    assert home[F["tilt_5"]] > 0.5
    # Over the match: every pass since kick-off (28 HOME, 15 AWAY), not just the last 10'.
    assert round(home[F["xt_match"]], 6) == 0.28
    assert round(away[F["xt_match"]], 6) == 0.15
    assert (home[F["shots_match"]], home[F["xg_match"]], home[F["opp_shots_match"]]) == (1, 0.25, 1)


def test_features_never_see_the_future() -> None:
    """Changing what happens after 20' changes nothing before it."""
    later = [shot(float(s), ShotOutcome.goal, team=AWAY) for s in range(1260, 1800, 30)]
    plain, changed = features(a_match()), features(a_match(later))
    before = [t for t in plain if t < 1260]
    assert len(before) > 30
    assert all(plain[t] == changed[t] for t in before)
    assert any(plain[t] != changed[t] for t in plain if t >= 1260)


def test_a_new_match_starts_over() -> None:
    tracker = FeatureTracker()
    totals: list[float] = []

    def on_step(_: Pipeline, step: Step) -> None:
        if step.tick is not None:
            totals.append(tracker.observe(step.tick)[HOME.id][F["xt_match"]])

    replay(a_match(), METRICS, on_step=on_step)
    first = list(totals)
    totals.clear()
    second = [e.model_copy(update={"match_id": 2}) for e in events_of(a_match())]
    replay(feed(second, match_id=2), METRICS, on_step=on_step)
    assert totals == first


def events_of(messages: list[FeedMessage]) -> list[MatchEvent]:
    return [m.event for m in messages if m.event is not None]
