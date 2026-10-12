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
| `ticks.py` | `Ticker`: picks a `Tick` (the match as of one event) every 30s of play, marked live or replayed |
| `hub.py` | `MatchHub`: the current match's history (snapshots and alerts since the last `MatchReset`) and live updates to subscribers, dropping any that fall too far behind |
| `detectors/` | `Detectors` (runs on each tick, cooldowns) and the `Momentum`, `GoalThreat` and `ControlShift` detectors |
| `sinks/` | `AlertSink` protocol, `LogSink`, and `WebhookSink` (background queue, retries with backoff) |
| `pipeline.py` | Feed message → reorder → clock → windows; tracks the two teams; handles `match_start`, `reset` and `match_end` |
| `api.py` | FastAPI app: `GET /api/stream` (server-sent events named `reset`, `status`, `snapshot`, `alert`), `/api/status`, `/api/metrics`, `/api/alerts`, and typed passthrough to the simulator (`/api/matches`, `/api/playback`, `POST /api/control`). Errors are `{"error": ...}`; the simulator's 4xx pass through, its failures are 502 |
| `runner.py`, `cli.py` | The async run loop (events → ticks → detectors → sinks for live alerts, and everything to the hub), `engine_status`, status report (with metrics) and command line (`--xt-grid`, `--webhook`) |

`src/engine/schema/` is generated from `schema/jsonschema/` by `make gen`. Do not edit it by hand.
