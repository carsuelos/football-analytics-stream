from engine.detectors import DetectorConfig, Detectors, Signal, Tick
from engine.metrics import MetricsConfig, XTGrid
from engine.pipeline import Pipeline
from engine.schema.alert_schema import Alert, AlertType
from engine.schema.event_schema import MatchEvent
from engine.schema.feed_schema import FeedMessage
from engine.schema.feed_schema import FeedMessageKind as K
from engine.windows import InMemoryStateStore
from tests.factories import AWAY, HOME, event, feed_event, feed_marker

METRICS = MetricsConfig(XTGrid.from_lists([[0.0] * 12] * 8))
GOAL, MOMENTUM = AlertType.goal_threat, AlertType.momentum_shift


class Fake:
    """Signals for the teams in `fire` on every tick, and records the ticks."""

    def __init__(self, type: AlertType = GOAL, fire: tuple[int, ...] = (HOME.id,)) -> None:
        self.type = type
        self.fire = fire
        self.ticks: list[tuple[int, float]] = []
        self.resets = 0

    def reset(self) -> None:
        self.resets += 1

    def evaluate(self, tick: Tick) -> list[Signal]:
        self.ticks.append((tick.item.event.period, tick.item.event.match_clock_s))
        return [
            Signal(t, value=1.0, threshold=0.5, window_s=300.4, features={"x": 2.0}, message=f"{t}")
            for t in self.fire
        ]


def match(*times: tuple[int, float]) -> list[MatchEvent]:
    """Events at the given (period, clock)s with offsets 0, 1, 2..., teams taking turns."""
    return [event(p, c, offset=i, team=(HOME, AWAY)[i % 2]) for i, (p, c) in enumerate(times)]


def every_30s(until_s: int) -> list[MatchEvent]:
    """An event every 30s of the first half: one tick each."""
    return match(*((1, float(s)) for s in range(0, until_s, 30)))


def start() -> FeedMessage:
    return feed_marker(K.match_start, 0)


def run(d: Detectors, *msgs: FeedMessage, pipeline: Pipeline | None = None) -> list[Alert]:
    p = pipeline or Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    return [a for msg in msgs for item in p.handle(msg) for a in d.observe(p, item)]


def events(es: list[MatchEvent]) -> list[FeedMessage]:
    return [feed_event(e) for e in es]


def clocks(alerts: list[Alert]) -> list[float]:
    return [a.match_clock_s for a in alerts]


def test_detectors_run_on_the_first_event_past_each_tick() -> None:
    fake = Fake()
    e = match((1, 0), (1, 10), (1, 29), (1, 30), (1, 45), (1, 61), (1, 200), (1, 205))
    run(Detectors([fake], METRICS), start(), *events(e))
    assert fake.ticks == [(1, 30), (1, 61), (1, 200)]


def test_ticks_count_play_time_across_half_time() -> None:
    fake = Fake()
    e = match((1, 0), (1, 20), (2, 2700), (2, 2705), (2, 2712))  # 2712 is 32s of play
    run(Detectors([fake], METRICS), start(), *events(e))
    assert fake.ticks == [(2, 2712)]


def test_the_shootout_has_no_ticks() -> None:
    fake = Fake()
    e = match((1, 0), (1, 10), (5, 0), (5, 40), (5, 80))
    run(Detectors([fake], METRICS), start(), *events(e))
    assert fake.ticks == []


def test_detectors_wait_for_both_teams() -> None:
    fake = Fake()
    e = [event(1, c, offset=i) for i, c in enumerate((0, 30, 60))]
    e += [event(1, 70, offset=3, team=AWAY), event(1, 90, offset=4)]
    run(Detectors([fake], METRICS), start(), *events(e))
    assert fake.ticks == [(1, 90)]  # not 70: that tick went by at 60


def test_the_cooldown_holds_back_repeats_per_detector_and_team() -> None:
    goal = Fake(GOAL, fire=(HOME.id, AWAY.id))
    momentum = Fake(MOMENTUM)
    alerts = run(Detectors([goal, momentum], METRICS), start(), *events(every_30s(700)))
    assert [(a.match_clock_s, a.type, a.team_id) for a in alerts] == [
        (t, type, team)
        for t in (30, 330, 630)  # 330 is exactly the 300s cooldown after 30
        for type, team in ((GOAL, HOME.id), (GOAL, AWAY.id), (MOMENTUM, HOME.id))
    ]


def test_the_tick_and_cooldown_are_configurable() -> None:
    fake = Fake()
    config = DetectorConfig(tick_s=60, cooldown_s=0)
    alerts = run(Detectors([fake], METRICS, config), start(), *events(every_30s(200)))
    assert clocks(alerts) == [60, 120, 180]


def test_no_alerts_while_catching_up_but_the_cooldowns_still_apply() -> None:
    e = every_30s(1000)
    live = run(Detectors([Fake()], METRICS), start(), *events(e))
    assert clocks(live) == [30, 330, 630, 930]

    # Connect when 15 events (up to 7:00) have been published. The tick at 330
    # is caught up on, so nothing comes out until its cooldown ends at 630.
    catch_up = feed_marker(K.match_start, 0, head=15)
    caught_up = run(Detectors([Fake()], METRICS), catch_up, *events(e))
    assert [a.id for a in caught_up] == [a.id for a in live[2:]]


def test_a_seek_starts_the_detectors_over_and_gives_the_same_alerts() -> None:
    e = every_30s(1000)
    live = run(Detectors([Fake()], METRICS), start(), *events(e))

    fake, p = Fake(), Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    d = Detectors([fake], METRICS)
    run(d, start(), *events(e[:25]), pipeline=p)
    assert fake.resets == 1
    seek = feed_marker(K.reset, 20, clock_s=600)  # back to 10:00, replaying from 0
    after_seek = run(d, seek, *events(e), pipeline=p)
    assert fake.resets == 2
    assert [a.id for a in after_seek] == [a.id for a in live if a.offset >= 20]


def test_a_reconnect_keeps_the_detectors_state() -> None:
    e = every_30s(1000)
    fake, p = Fake(), Pipeline(InMemoryStateStore(), allowed_lateness_s=0)
    d = Detectors([fake], METRICS)
    assert clocks(run(d, start(), *events(e[:12]), pipeline=p)) == [30, 330]
    resume = feed_marker(K.match_start, 12, head=12)
    assert clocks(run(d, resume, *events(e[12:]), pipeline=p)) == [630, 930]
    assert fake.resets == 1


def test_an_alert_carries_the_signal_and_the_event_that_raised_it() -> None:
    alerts = run(
        Detectors([Fake(fire=(AWAY.id,))], METRICS), start(), *events(match((1, 0), (1, 31.5)))
    )
    assert alerts == [
        Alert(
            schema_version=1,
            id="1-goal_threat-2-1",
            match_id=1,
            offset=1,
            period=1,
            match_clock_s=31.5,
            type=GOAL,
            team_id=AWAY.id,
            value=1.0,
            threshold=0.5,
            window_s=300,
            features={"x": 2.0},
            message="2",
        )
    ]
