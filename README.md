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
make fetch-data ARGS="--match-id 3869685"     # 2022 World Cup final (omit ARGS for all 64 matches)
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

## Data attribution

Match data comes from [StatsBomb Open Data](https://github.com/statsbomb/open-data) and is used under their non-commercial terms. Data files are downloaded locally and never committed.
