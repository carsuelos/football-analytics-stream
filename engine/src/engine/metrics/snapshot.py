"""A MetricSnapshot: every metric for both teams over one window."""

from dataclasses import dataclass, field

from engine.metrics.field_tilt import field_tilt
from engine.metrics.pressure import PressureWeights, pressure
from engine.metrics.xt import XTGrid, xt_added, xt_velocity
from engine.schema.metric_schema import MetricSnapshot, TeamMetrics
from engine.windows import SlidingWindows


@dataclass(frozen=True)
class MetricsConfig:
    """What the metrics need beyond the events themselves."""

    grid: XTGrid
    weights: PressureWeights = field(default_factory=PressureWeights)


def snapshot(
    windows: SlidingWindows, length_s: float, team_ids: tuple[int, int], config: MetricsConfig
) -> MetricSnapshot | None:
    """Metrics over the window of length_s ending now; None before the first event."""
    latest = windows.latest
    if latest is None:
        return None
    events = [i.event for i in windows.events(length_s)]
    tilt = field_tilt(events, team_ids)
    xt = xt_added(events, team_ids, config.grid)
    press = pressure(events, team_ids)
    covered_s = windows.covered_s(length_s)
    return MetricSnapshot(
        schema_version=1,
        match_id=windows.match_id,
        offset=latest.event.offset,
        period=latest.event.period,
        match_clock_s=latest.event.match_clock_s,
        window_s=round(length_s),
        teams=[
            TeamMetrics(
                team_id=t,
                field_tilt=tilt[t],
                xt_added=xt[t],
                xt_velocity=xt_velocity(xt[t], covered_s),
                pressure_index=press[t].index(config.weights),
            )
            for t in team_ids
        ],
    )
