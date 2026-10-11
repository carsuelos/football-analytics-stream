# Live Football Analytics Stream

Real-time football analytics: a Go simulator replays StatsBomb match events as a live feed, a Python engine computes rolling metrics (field tilt, xT velocity, sustained pressure) and tactical alerts, and a React dashboard shows them as the match unfolds.

- Plan and roadmap: [docs/PLAN.md](docs/PLAN.md)
- Vision and decisions: [docs/copilot_context.md](docs/copilot_context.md)

## Layout

| Path | What |
| --- | --- |
| `schema/jsonschema/` | JSON Schemas: the contract between all components (single source of truth) |
| `schema/fixtures/` | Example messages (`valid/`, `invalid/`) tested in every language |
| `simulator/` | Go: replays StatsBomb events over WebSocket |
| `engine/` | Python (uv): metrics, windows, alerts |
| `dashboard/` | React + Vite + TypeScript (pnpm) |
| `scripts/` | Data fetch and offline tooling |
| `data/` | Local StatsBomb cache (gitignored) |

## Prerequisites

Go 1.27+, [uv](https://docs.astral.sh/uv/), Node 26 + pnpm 12, GNU Make. Docker is needed from Phase 2.

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
| `make engine` | Run the engine against the simulator feed (`ARGS="--help"` lists options) |

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
curl -XPOST localhost:8080/control -d '{"schema_version": 1, "command": "load_match", "match_id": 3869685}'   # terminal 3
curl -XPOST localhost:8080/control -d '{"schema_version": 1, "command": "set_speed", "speed": 60}'
curl -XPOST localhost:8080/control -d '{"schema_version": 1, "command": "play"}'
```

Every second the engine logs where the match is and how many events it has released, held back, or dropped as late or duplicate. For each of the last 5 and 10 minutes of play it also logs each team's field tilt, xT added (and per minute) and pressure index:

```text
match 3869685 P2 82:30 (play 90:04) | released 2993 buffered 9 late 0 dup 0
  last 5': Argentina tilt 0% xT -0.00 (-0.001/min) pressure 0.0 | France tilt 100% xT +0.14 (+0.028/min) pressure 11.0
  last 10': Argentina tilt 58% xT +0.07 (+0.007/min) pressure 8.5 | France tilt 42% xT +0.17 (+0.017/min) pressure 11.8
```

The metric definitions are in [docs/PLAN.md](docs/PLAN.md#metric-definitions-v1). Try:

- a seek (`{"schema_version": 1, "command": "seek", "seek_to": {"period": 2, "match_clock_s": 4500}}`): the engine rebuilds its windows from a replay;
- `make engine ARGS="--allowed-lateness 1"` with `-jitter 3s`: events arriving more than 1s late are dropped and counted;
- stopping and restarting the simulator: the engine reconnects and resumes from its last offset;
- `make engine ARGS="--xt-grid path/to/grid.json"`: use a different 12×8 xT grid.

## Data attribution

Match data comes from [StatsBomb Open Data](https://github.com/statsbomb/open-data) and is used under their non-commercial terms. Data files are downloaded locally and never committed.

The expected-threat (xT) grid is Karun Singh's, from [Introducing Expected Threat (xT)](https://karun.in/blog/expected-threat.html). It is downloaded by `make fetch-data` and not redistributed here.
