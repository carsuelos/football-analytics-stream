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
| `pipeline.py` | Feed message → reorder → clock → windows; handles `match_start`, `reset` and `match_end` |
| `runner.py`, `cli.py` | The async run loop, status line and command line |

`src/engine/schema/` is generated from `schema/jsonschema/` by `make gen`. Do not edit it by hand.
