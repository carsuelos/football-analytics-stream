# Live Football Analytics Stream

Real-time football analytics: a Go simulator replays StatsBomb match events as a live feed, a Python engine computes rolling metrics (field tilt, xT velocity, sustained pressure) and tactical alerts, and a React dashboard shows them as the match unfolds.

- Plan and roadmap: [docs/PLAN.md](docs/PLAN.md)
- Vision and decisions: [docs/copilot_context.md](docs/copilot_context.md)
- Modeling: techniques and results in [docs/MODEL.md](docs/MODEL.md)

## Layout

| Path | What |
| --- | --- |
| `schema/jsonschema/` | JSON Schemas: the contract between all components (single source of truth) |
| `schema/fixtures/` | Example messages (`valid/`, `invalid/`) tested in every language |
| `simulator/` | Go: replays StatsBomb events as a live broadcast, over WebSocket and Kafka, and downloads more matches from StatsBomb's open data for the dashboard (`internal/library`); `cmd/export` writes them to files for offline replay |
| `engine/` | Python (uv): metrics, windows, alerts; `engine.backtest` replays exported feeds offline |
| `model/` | Python (uv): offline modeling on the exported feeds (our own xT grid, the goal model's dataset and models); see [docs/MODEL.md](docs/MODEL.md) |
| `notifier/` | Go: delivers the alerts from Kafka to webhooks |
| `markets/` | Go: the prediction markets' prices (Kalshi, Polymarket US, Novig) for Premier League and La Liga games, for the dashboard's Markets page |
| `dashboard/` | React + Vite + TypeScript (pnpm) |
| `scripts/` | Data fetch and offline tooling |
| `data/` | Local StatsBomb cache (gitignored) |
| `compose.yaml` | Docker Compose: the whole stack (each service has its own `Dockerfile`) |
| `infra/` | Bicep: the Azure resources (`bootstrap/`, run once by an Owner, then `main.bicep`, deployed by `.github/workflows/deploy.yml`); see [docs/AZURE.md](docs/AZURE.md) |

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
| `make ci` | What CI runs, except the Compose smoke test (`make smoke-compose`) |
| `make sim` | Run the simulator on `:8080` (`ARGS="-jitter 3s"` delivers events up to 3s late) |
| `make engine` | Run the engine against the simulator and serve its API on `:8000` (`ARGS="--help"` lists options) |
| `make dashboard` | Run the dashboard on `:5173`, proxying `/api` to the engine on `:8000` |
| `make smoke` | End-to-end smoke test: replay the 2022 final through the simulator and engine at 1000× and check the metrics and alerts (`ARGS="--sample"` adds 10 random matches; `ARGS="--match ID"` for another match) |
| `make fetch-training` | Download and export the model's training data into `data/training/` (2,552 matches from every men's senior season since 2003 except the 2022 World Cup; about 10 GB, a few minutes) |
| `make export` | Write every downloaded match as the simulator broadcasts it to `data/feeds/`, one JSON message per line, for offline replay (under a second for 64 matches) |
| `make backtest` | Replay every exported match through the engine offline (no simulator, clock or network) and print each one's score and alerts |
| `make evaluate` | Replay the 64 2022 World Cup matches offline and measure whether the alerts (the rules and the goal model) predict goals (a few seconds; `ARGS="--sample N --seed S"` for a subset) |
| `make xt` | Fit our own xT grid on the training data and compare it with the published one on the World Cup (needs `make fetch-training`) |
| `make dataset` | Build the goal model's features and labels (each team every 30 seconds) from the training and World Cup feeds into `data/model/` (about 2 minutes) |
| `make train` | Train and compare the goal models (base rate, logistic regression, gradient-boosted trees) and score them on the World Cup (about 2 minutes) |
| `make rules` | Retune the three rules (momentum, goal threat, control shift) on the training data and score them on the World Cup, checking the engine raises exactly the simulated alerts; prints the new defaults (about 20 minutes, 5 of them recording the first time) |
| `make export-model` | Fit the shipped goal model on all the training data and write it into the engine (`engine/src/engine/detectors/goal_model.json`), checking the engine computes what scikit-learn fitted (about 15 seconds) |
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

The engine serves its API on `http://localhost:8000` (`--simulator` sets where the simulator is, or `--no-simulator` says there is none; `--host` and `--port` where to listen):

- `GET /api/stream`: server-sent events. A `reset`, the latest `status` (with the score), the match so far (a `snapshot` every 5s of play, each `alert`, and each `incident`: goals, cards, penalties and shootout kicks, each with the score after it), then updates as they happen.
- `GET /api/status`, `/api/metrics`, `/api/alerts`, `/api/incidents`: the same, once.
- `GET /api/matches`, `GET /api/broadcast`, `POST /api/broadcast`: passed through to the simulator (the broadcaster: load a match, play, pause, speed), so the dashboard only talks to the engine. With `--no-simulator` they answer 404 `no simulator`, and the dashboard hides its simulator controls.
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
ALERT P3 106:00 control_shift: Argentina in control: pressure balance +0.82 over the last 5', from -0.53 the 5' before
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

The dashboard has two kinds of controls, kept apart on purpose:

- **Simulator** (the dashed panel at the top): the simulator stands in for a live feed, so this is the "TV studio". Choose a match and its broadcast starts, in real time; pick 60× to play a half in under a minute, or Pause to hold it. **+ Add matches** downloads any competition season in StatsBomb's open data (search "euro 2025", say) into the simulator in the background, and its matches join the list as they arrive; no script needed. A real feed can't be paused or sped up, so when the engine has no simulator (`--no-simulator`) the panel is hidden and the match is whatever the feed is playing.
- **Viewer**: your view of the broadcast, as on a TV box. These work on any feed: pause, rewind to any minute up to the live edge (the engine rebuilds the charts and alerts up to there), catch up at a faster speed, or jump back to live. The badge shows "LIVE" or how far behind it you are.

The switch at the top right turns on a light theme (remembered in your browser). New alerts pop up at the top right with a ding (the speaker button mutes it); **Notify me** also shows them as Mac notifications while the dashboard's window is in the background (the browser asks for permission the first time). Safari labels a website's notifications with its own icon; add the dashboard to the Dock (Safari ▸ File ▸ Add to Dock) and it becomes an app of its own, with the pitch icon on its notifications. A compact scoreboard heads the match timeline: the score (and the shootout's), the clock to the second and each team's goals and red cards. The timeline puts every goal, card, penalty and alert along the match, in one compact row until clicked (it then stacks markers that are close); hover a marker for what it is. The charts show each team's field tilt, xT added and pressure index over the last 5 or 10 minutes, with goals and alerts marked. The match feed on the right lists events and alerts together (toggle alerts, goals, cards and penalties) and says, for each alert, whether that team went on to score within 10 minutes. That verdict comes later, as the match plays on: the engine only ever sends what has happened up to the viewer's position, so after a seek back the later goals are gone until they are replayed. Stop the engine and restart it: it catches up with the broadcast, and the dashboard reconnects by itself.

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

To see the dashboard as it would be on a real feed, with nothing to control, run a second engine on the stack's Kafka with no simulator, and a dev dashboard on it:

```sh
KAFKA_BOOTSTRAP_SERVERS=localhost:19092 make engine ARGS="--source kafka --no-simulator --port 8001"
ENGINE_URL=http://localhost:8001 make dashboard   # http://localhost:5173: no Simulator panel
```

It follows whatever match the stack's simulator is broadcasting (start one at http://localhost:3000). It also publishes its metrics and alerts, which the notifier drops as repeats.

The engine publishes back to the broker too: each metrics snapshot to `metrics` and each alert to `alerts`, keyed by match (`docker compose exec redpanda rpk topic consume alerts -n 1`). Only live play is published, not the catch-up after a restart, but a viewer rewatching through the DVR publishes that stretch again, so consumers drop repeats (alerts by `id`, snapshots by match, offset and window).

The **notifier** (`notifier/`, Go) consumes `alerts` as the `notifier` consumer group and POSTs each alert as JSON to every `-webhook` (by default the `webhook` service, which prints them: `docker compose logs -f webhook`; set `ALERT_WEBHOOK` for a real one). It delivers at least once: an alert's offset is committed only once delivered, so a restart resumes where it left off. Repeats are dropped by alert id, and each request carries an `Idempotency-Key: <alert id>` header for the receiver to drop the rare repeat after a restart. A failing webhook (network error, 5xx or 429) is retried with backoff until the alert is older than `-max-age` (5 minutes), since a late alert is no use; other 4xx errors are not retried. A new consumer group starts from the earliest alert but skips the stale ones the same way.

### Logs and traces

Every app logs to stderr: as text by default, or one JSON object a line with `LOG_FORMAT=json` (what Azure's log collector expects). A line logged inside a traced operation carries its `trace_id` and `span_id`.

Tracing is off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Then each app exports spans over OTLP/gRPC, configured by the standard [`OTEL_*` variables](https://opentelemetry.io/docs/languages/sdk-configuration/). The trace context travels in W3C `traceparent` headers, over HTTP and in Kafka message headers, so one alert is one trace across all three apps:

```text
simulator  send events            (the event that completed the tick)
engine       receive events
engine         alert momentum_shift
engine           send alerts
notifier           process alerts
notifier             HTTP POST     (the webhook)
```

`make up` sends the traces to the [Aspire dashboard](https://aspire.dev/dashboard/standalone/) at http://localhost:18888 (`ASPIRE_PORT`), a free OTLP viewer. In Azure they go to Application Insights through the Container Apps OpenTelemetry agent; the code knows nothing about either. The engine's API requests and its calls to the simulator are traced too, but not the event stream (it lasts as long as the connection) or health checks.

### The prediction markets

The dashboard's **Markets** page (http://localhost:3000/#/markets with `make up`) shows the Premier League's and La Liga's games as Kalshi, Polymarket US and Novig list them:
- which venues list each game;
- the live score and clock;
- each venue's price to buy each contract (total goals over 0.5 to 6.5, the result, and each team's goals over 0.5 to 3.5, all after 90' plus stoppage), with its bid and fee; each kind folds away;
- the cheapest all-in price (the ask plus the venue's fee), and how it has moved.

It reads the venues' public data through the `markets` service, so it needs no accounts or keys. While `make up` runs, it also records every game's prices to `data/markets` (every 10 s while a game is live), so trading strategies can be replayed later against real prices. Leaving it running costs little: tens of MB a busy weekend, under 1 GB a month. While the Mac sleeps nothing is recorded (it picks up on waking); to keep it awake on power, run `caffeinate -s` in a terminal (Ctrl-C to stop), or turn on System Settings ▸ Battery ▸ Options ▸ "Prevent automatic sleeping on power adapter when the display is off". `make tape` lists what's recorded, and `make tape ARGS="--game <id> --contract total-over-2.5"` prints a contract's prices as CSV. Our model's probability and paper trading join it with a live event feed. Outside Docker: `make markets`, then `make dashboard`.

### Running it in Azure

```sh
make cloud-up       # deploys from main with GitHub Actions (about 5 minutes), then prints the URL
make cloud-down     # when you're done; it also goes down every night
```

The same stack, on Azure Container Apps behind a password, with Event Hubs as the broker and traces in Application Insights. It costs about $0.15 an hour while up and about $5 a month while down. How it's built, deployed and observed: [docs/AZURE.md](docs/AZURE.md).

### Smoke test

`make smoke` builds the simulator, starts it and the engine on ports 18080 and 18000 (so your dev setup can keep running), and replays the 2022 final at 1000× (about 10 s). The simulator delivers events up to 3 s late, so the engine has to reorder them. Every match is checked for consistency: the right teams, nothing dropped or duplicated, field tilts adding up to 1, snapshots in match-time order, alerts at or above their thresholds, and no errors in the logs. The final is also checked against what happened: Argentina's first-half dominance, penalties, and a goal-threat alert *before* each comeback goal (France's at 79', Messi's at 108').

- `make smoke ARGS="--sample"`: the final and 10 random other matches, on the same processes, so switching matches is tested too. A failing sample is reproduced with the `--seed` it printed.
- `make smoke ARGS="--match 3857256"`: another match (`--match` can be repeated).
- `make smoke-compose`: the same checks against the Docker stack (so over Kafka), started with events up to 3 s late, through the dashboard's proxy, plus a check that the notifier delivered every alert to the `webhook` service exactly once, as the engine raised it (rewatch included). Its logs are not checked (see `make logs`). CI runs this on every push, with the final's data.

A failure prints what went wrong and where the processes' logs are.

### Do the alerts predict goals?

Not yet. `make evaluate` replays all 64 World Cup matches through the engine and compares every alert with the goals that followed. The lift is how much more often the alerted team scores in the next 5 or 10 minutes than a team does in any 5 or 10 minutes: 1.0 means no better than chance. The Phase 1 alerts score about 0.9–1.2, so for now they describe a shift in the game rather than forecast a goal. A trained model that beats chance is the Phase 3 goal (see [the plan](docs/PLAN.md)).

The replay is offline: `make export` has the simulator write each match exactly as it would broadcast it (`simulator/cmd/export`), and the engine's `engine.backtest` feeds those messages through the same pipeline, ticker and detectors it runs live, as fast as the CPU allows. The alerts are the ones the engine raises live (a test checks this), so the whole tournament takes seconds instead of hours, and the same replay produces the model's training data.

## Data attribution

Match data comes from [StatsBomb Open Data](https://github.com/statsbomb/open-data) and is used under their non-commercial terms. Data files are downloaded locally and never committed. The model is trained on StatsBomb's other men's competitions (`make fetch-training`) and tested on the 2022 World Cup, which it never sees in training.

The expected-threat (xT) grid is Karun Singh's, from [Introducing Expected Threat (xT)](https://karun.in/blog/expected-threat.html). It is downloaded by `make fetch-data` and not redistributed here. Our own grid, `model/artifacts/xt_statsbomb_12x8.json`, is fitted on StatsBomb Open Data with the same method (see [docs/MODEL.md](docs/MODEL.md)).
