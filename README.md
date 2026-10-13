# Live Football Analytics Stream

Real-time football analytics: a Go simulator replays StatsBomb match events as a live feed, a Python engine computes rolling metrics (field tilt, xT velocity, sustained pressure) and tactical alerts, and a React dashboard shows them as the match unfolds.

- Plan and roadmap: [docs/PLAN.md](docs/PLAN.md)
- Vision and decisions: [docs/copilot_context.md](docs/copilot_context.md)

## Layout

| Path | What |
| --- | --- |
| `schema/jsonschema/` | JSON Schemas: the contract between all components (single source of truth) |
| `schema/fixtures/` | Example messages (`valid/`, `invalid/`) tested in every language |
| `simulator/` | Go: replays StatsBomb events as a live broadcast, over WebSocket and Kafka |
| `engine/` | Python (uv): metrics, windows, alerts |
| `dashboard/` | React + Vite + TypeScript (pnpm) |
| `scripts/` | Data fetch and offline tooling |
| `data/` | Local StatsBomb cache (gitignored) |
| `compose.yaml` | Docker Compose: the whole stack (each service has its own `Dockerfile`) |

## Prerequisites

Go 1.27+, [uv](https://docs.astral.sh/uv/), Node 26 + pnpm 12, GNU Make. Docker (with Compose) to run the whole stack in containers.

## Getting started

```sh
make setup                                    # install dependencies
make fetch-data ARGS="--match-id 3869685"     # 2022 World Cup final (omit ARGS for all 64 matches) + the xT grid
make test                                     # all tests, including schema contract tests
```

| Target | Does |
| --- | --- |
| `make gen` | Regenerate Go, Python and TS types from `schema/jsonschema/` |
| `make check-gen` | Fail if generated code is out of date (run in CI) |
| `make lint` | gofmt, go vet, ruff, mypy, oxlint, tsc |
| `make test` | go test, pytest, vitest |
| `make fmt` | Auto-format Go and Python |
| `make ci` | Everything CI runs |
| `make sim` | Run the simulator on `:8080` (`ARGS="-jitter 3s"` delivers events up to 3s late) |
| `make engine` | Run the engine against the simulator and serve its API on `:8000` (`ARGS="--help"` lists options) |
| `make dashboard` | Run the dashboard on `:5173`, proxying `/api` to the engine on `:8000` |
| `make smoke` | End-to-end smoke test: replay the 2022 final through the simulator and engine at 1000× and check the metrics and alerts (`ARGS="--sample"` adds 10 random matches; `ARGS="--match ID"` for another match) |
| `make evaluate` | Replay 20 matches and measure whether the alerts predict goals (about 3 minutes; `ARGS="--sample N --seed S"` for others) |
| `make webhook` | Run a webhook receiver on `:9000` that prints the alerts it gets |
| `make up` / `make down` | Build and start the whole stack in Docker (dashboard on `:3000`) / stop it |
| `make logs` | Follow the Docker stack's logs |
| `make smoke-compose` | The smoke test against the Docker stack |

Generated code is committed. After editing a schema, run `make gen` and commit the result.

### Driving the simulator by hand

```sh
make sim                                                            # terminal 1
curl localhost:8080/matches                                         # terminal 2
curl -XPOST localhost:8080/control -d '{"schema_version": 1, "command": "load_match", "match_id": 3869685}'
curl -XPOST localhost:8080/control -d '{"schema_version": 1, "command": "set_speed", "speed": 60}'
curl -XPOST localhost:8080/control -d '{"schema_version": 1, "command": "play"}'
curl localhost:8080/status
```

The live feed is a WebSocket at `ws://localhost:8080/feed` (add `?from_offset=N` to resume).

### Running the engine against the simulator

```sh
make sim ARGS="-jitter 3s"                                          # terminal 1
make engine                                                         # terminal 2
curl -N localhost:8000/api/stream                                   # terminal 3
curl --json '{"schema_version": 1, "command": "load_match", "match_id": 3869685}' localhost:8000/api/broadcast   # terminal 4
curl --json '{"schema_version": 1, "command": "set_speed", "speed": 60}' localhost:8000/api/broadcast
curl --json '{"schema_version": 1, "command": "play"}' localhost:8000/api/broadcast
```

The engine serves its API on `http://localhost:8000` (`--simulator` sets where the simulator is, `--host` and `--port` where to listen):

- `GET /api/stream`: server-sent events. A `reset`, the latest `status`, the match so far (a `snapshot` every 30s of play, and each `alert`), then updates as they happen.
- `GET /api/status`, `/api/metrics`, `/api/alerts`: the same, once.
- `GET /api/matches`, `GET /api/broadcast`, `POST /api/broadcast`: passed through to the simulator (the broadcaster: load a match, play, pause, speed), so the dashboard only talks to the engine.
- `POST /api/control`: the viewer's controls. The engine is a DVR over the broadcast: `pause`, `play`, `set_speed` (while behind live), `seek` to any point up to the live edge, and `go_live`. It replies with the engine's status, which also shows the live edge and how far behind it the viewer is (`behind_live_s`).

`POST` bodies must be sent as JSON (`curl --json`, not `-d`).

With `ARGS="--log-level DEBUG"`, every second the engine also logs where the match is and how many events it has released, held back, or dropped as late or duplicate. For each of the last 5 and 10 minutes of play it also logs each team's field tilt, xT added (and per minute) and pressure index:

```text
match 3869685 P2 82:30 (play 90:04) | released 2993 buffered 9 late 0 dup 0
  last 5': Argentina tilt 0% xT -0.00 (-0.001/min) pressure 0.0 | France tilt 100% xT +0.14 (+0.028/min) pressure 11.0
  last 10': Argentina tilt 58% xT +0.07 (+0.007/min) pressure 8.5 | France tilt 42% xT +0.17 (+0.017/min) pressure 11.8
```

When a detector fires, the engine logs an alert:

```text
ALERT P2 82:27 control_shift: France taking control: pressure balance +0.69 over the last 5', from -0.54 the 5' before
```

The metric definitions are in [docs/PLAN.md](docs/PLAN.md#metric-definitions-v1), and the alert definitions in [Predictive signals](docs/PLAN.md#predictive-signals-v1-rule-based). Try:

- a seek back to `/api/control` (`{"schema_version": 1, "command": "seek", "seek_to": {"period": 2, "match_clock_s": 4500}}`): the engine rebuilds its windows from its copy of the match and plays on from 75:00 while the broadcast carries on; `{"schema_version": 1, "command": "go_live"}` catches up;
- `make engine ARGS="--allowed-lateness 1"` with `-jitter 3s`: events arriving more than 1s late are dropped and counted;
- stopping and restarting the simulator: the engine reconnects and resumes from its last offset;
- `make engine ARGS="--xt-grid path/to/grid.json"`: use a different 12×8 xT grid;
- `make webhook` in another terminal and `make engine ARGS="--webhook http://localhost:9000"`: each alert is also POSTed as JSON. `make webhook ARGS="--fail 2"` answers the first 2 requests with 503, so you can watch the engine retry.

### Watching a match in the dashboard

```sh
make sim                                                            # terminal 1
make engine                                                         # terminal 2
make dashboard                                                      # terminal 3, then open http://localhost:5173
```

Choose a match, pick a speed (60× plays a half in under a minute) and press Play. That drives the broadcast. The viewer controls below it drive your view of it, as on a TV box: pause, rewind to any minute up to the live edge (the engine rebuilds the charts and alerts up to there), catch up at a faster speed, or jump back to live. The badge shows "LIVE" or how far behind it you are. The charts show each team's field tilt, xT added and pressure index over the last 5 or 10 minutes; a line marks each alert, and the feed on the right explains it. The header shows the match clock, what the engine is doing, and whether the dashboard is connected. Stop the engine and restart it: it catches up with the broadcast, and the dashboard reconnects by itself.

### Running it all in Docker

```sh
make fetch-data ARGS="--match-id 3869685"   # once: the data is mounted, never baked into images
make up                                     # then open http://localhost:3000
make down
```

Compose (`compose.yaml`) runs each service from its own image: the simulator on a distroless base, the engine in a slim Python image, and the dashboard's build served by nginx, which proxies `/api` (including the event stream, unbuffered) to the engine. The simulator and engine are also published on `:8080` and `:8000`. `SIM_JITTER=3s make up` delivers events up to 3 s late; `SIM_PORT`, `ENGINE_PORT` and `DASHBOARD_PORT` move the published ports.

In Docker the broadcast goes through Kafka, as it would from a real data provider: the simulator publishes every match it broadcasts to an `events` topic on [Redpanda](https://redpanda.com) (keyed by match, so each match stays in order on one partition), and the engine reads it from there (`--source kafka`). A one-shot `topics` service creates the topic; the apps never do. The engine commits nothing: when it starts, it finds the latest `match_start` on the topic, catches up to the end without raising alerts, then follows live, so `docker compose restart engine` mid-match picks up where the broadcast is. Redpanda is published on `localhost:19092` (`KAFKA_PORT`), e.g. `docker compose exec redpanda rpk topic consume events -n 3`.

Both apps take their Kafka client settings from `KAFKA_*` environment variables, each mapping to a [librdkafka property](https://github.com/confluentinc/librdkafka/blob/master/CONFIGURATION.md) (`KAFKA_BOOTSTRAP_SERVERS` → `bootstrap.servers`). Outside Docker, the simulator publishes when `KAFKA_BOOTSTRAP_SERVERS` is set (`-kafka-topic` names the topic), and `make engine ARGS="--source kafka"` reads it. Only standard Kafka is used, so another cluster is config only; for Azure Event Hubs:

```sh
KAFKA_BOOTSTRAP_SERVERS=<namespace>.servicebus.windows.net:9093
KAFKA_SECURITY_PROTOCOL=SASL_SSL
KAFKA_SASL_MECHANISM=PLAIN
KAFKA_SASL_USERNAME='$ConnectionString'
KAFKA_SASL_PASSWORD='<connection string>'
```

The engine follows one match at a time: the one most recently started.

### Smoke test

`make smoke` builds the simulator, starts it and the engine on ports 18080 and 18000 (so your dev setup can keep running), and replays the 2022 final at 1000× (about 10 s). The simulator delivers events up to 3 s late, so the engine has to reorder them. Every match is checked for consistency: the right teams, nothing dropped or duplicated, field tilts adding up to 1, snapshots in match-time order, alerts at or above their thresholds, and no errors in the logs. The final is also checked against what happened: Argentina's first-half dominance, penalties, and a goal-threat alert *before* each comeback goal (France's at 79', Messi's at 108').

- `make smoke ARGS="--sample"`: the final and 10 random other matches, on the same processes, so switching matches is tested too. A failing sample is reproduced with the `--seed` it printed.
- `make smoke ARGS="--match 3857256"`: another match (`--match` can be repeated).
- `make smoke-compose`: the same checks against the Docker stack (so over Kafka), started with events up to 3 s late, through the dashboard's proxy. Its logs are not checked (see `make logs`).

A failure prints what went wrong and where the processes' logs are.

### Do the alerts predict goals?

Not yet. `make evaluate` replays 20 matches the same way and compares every alert with the goals that followed. The lift is how much more often the alerted team scores in the next 5 or 10 minutes than a team does in any 5 or 10 minutes: 1.0 means no better than chance. The Phase 1 alerts score about 0.7–1.2, so for now they describe a shift in the game rather than forecast a goal. A trained model that beats chance is the Phase 3 goal (see [the plan](docs/PLAN.md)).

## Data attribution

Match data comes from [StatsBomb Open Data](https://github.com/statsbomb/open-data) and is used under their non-commercial terms. Data files are downloaded locally and never committed.

The expected-threat (xT) grid is Karun Singh's, from [Introducing Expected Threat (xT)](https://karun.in/blog/expected-threat.html). It is downloaded by `make fetch-data` and not redistributed here.
