# engine

Python analytics engine: consumes the simulator feed, maintains rolling windows, computes metrics and raises alerts.

```sh
uv run engine --help    # or `make engine` from the repo root
```

| Package | Does |
| --- | --- |
| `sources/` | `EventSource` protocol. `WebSocketSource`: reads the simulator feed, reconnects and resumes from the last offset. `KafkaSource`: reads the `events` topic, starting from the latest `match_start` (caught up without alerts) and following whichever match starts next; commits nothing. `config_from_env` maps `KAFKA_*` variables to librdkafka settings; `confluent.py` is the librdkafka adapter |
| `clock/` | `ReorderBuffer` (watermark, late drops, dedupe) and `MatchClock` (continuous play time) |
| `windows/` | `StateStore` protocol, `InMemoryStateStore`, and 5/10-minute `SlidingWindows` |
| `metrics/` | Pure per-window metrics: `field_tilt`, `xt_added`/`xt_velocity` (`XTGrid`), `pressure` (`PressureWeights`), and `snapshot`, which builds a schema `MetricSnapshot` |
| `ticks.py` | `Ticker`: picks a `Tick` (the match as of one event) every 30s of play, marked live or replayed |
| `hub.py` | `MatchHub`: the current match's history (snapshots and alerts since the last `MatchReset`) and live updates to subscribers, dropping any that fall too far behind; `close` ends every stream on shutdown |
| `detectors/` | `Detectors` (runs on each tick, cooldowns) and the `Momentum`, `GoalThreat` and `ControlShift` detectors |
| `sinks/` | `AlertSink` and `MetricSink` protocols, `LogSink`, `WebhookSink` (background queue, retries with backoff), and `KafkaAlertSink`/`KafkaMetricSink` on a shared `KafkaPublisher` (keyed by `match_id`; used when `KAFKA_BOOTSTRAP_SERVERS` is set; `ConfluentProducer` is the librdkafka adapter) |
| `dvr.py` | `Dvr`: the viewer over the broadcast. Keeps the current match's feed in memory and replays it to the pipeline: live, paused, or playing at the viewer's speed from any point up to the live edge; a seek back starts the match over from its copy |
| `pipeline.py` | Feed message → reorder → clock → windows; tracks the two teams; handles `match_start` (a resume, a catch-up or a start over) and `match_end` |
| `api.py` | FastAPI app: `GET /api/stream` (server-sent events named `reset`, `status`, `snapshot`, `alert`), `/api/status`, `/api/metrics`, `/api/alerts`, and typed passthrough to the simulator (`/api/matches`, `GET`/`POST /api/broadcast`), and the viewer's controls on the DVR (`POST /api/control`). Errors are `{"error": ...}`; the simulator's 4xx pass through, its failures are 502 |
| `runner.py`, `cli.py` | The async run loop (events → ticks → detectors → sinks for live alerts and snapshots, and everything to the hub), `engine_status`, status report (with metrics) and command line: uvicorn serves the API with the run loop alongside it (`--simulator` or `--no-simulator`, `--source ws|kafka`, `--kafka-topic`, `--alerts-topic`, `--metrics-topic`, `--host`, `--port`, `--xt-grid`, `--webhook`; the status report logs at DEBUG) |

`src/engine/schema/` is generated from `schema/jsonschema/` by `make gen`. Do not edit it by hand.
