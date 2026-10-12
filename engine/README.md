# engine

Python analytics engine: consumes the simulator feed, maintains rolling windows, computes metrics and raises alerts.

```sh
uv run engine --help    # or `make engine` from the repo root
```

| Package | Does |
| --- | --- |
| `sources/` | `WebSocketSource`: reads the simulator feed, reconnects and resumes from the last offset |
| `clock/` | `ReorderBuffer` (watermark, late drops, dedupe) and `MatchClock` (continuous play time) |
| `windows/` | `StateStore` protocol, `InMemoryStateStore`, and 5/10-minute `SlidingWindows` |
| `metrics/` | Pure per-window metrics: `field_tilt`, `xt_added`/`xt_velocity` (`XTGrid`), `pressure` (`PressureWeights`), and `snapshot`, which builds a schema `MetricSnapshot` |
| `detectors/` | `Detectors` (30s play-time tick, cooldowns, silent replays) and the `Momentum`, `GoalThreat` and `ControlShift` detectors |
| `sinks/` | `AlertSink` protocol, `LogSink`, and `WebhookSink` (background queue, retries with backoff) |
| `pipeline.py` | Feed message → reorder → clock → windows; tracks the two teams; handles `match_start`, `reset` and `match_end` |
| `runner.py`, `cli.py` | The async run loop (events → detectors → sinks), status report (with metrics) and command line (`--xt-grid`, `--webhook`) |

`src/engine/schema/` is generated from `schema/jsonschema/` by `make gen`. Do not edit it by hand.
