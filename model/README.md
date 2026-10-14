# model

Offline modeling for the engine: what makes a goal likely, learnt from StatsBomb data the engine never sees live. Everything here reads the feeds `make export` writes (the simulator's broadcast, in the canonical schema), so what the model learns from is exactly what the engine sees.

The techniques, the results of each step and how to iterate on them are in [docs/MODEL.md](../docs/MODEL.md).

| Module | What |
| --- | --- |
| `model.xt` | Our own expected-threat (xT) grid: Karun Singh's Markov model, fitted on the training matches and compared with the published grid on the World Cup (`make xt`) |
| `model.dataset` | The goal model's rows: each team every 30 seconds from 15', with the engine's features (`engine.features`) and whether it scores in the next 5 and 10 minutes, into `data/model/{train,test}.npz` (`make dataset`) |

| Artifact | What |
| --- | --- |
| `artifacts/xt_statsbomb_12x8.json` | Our 12×8 xT grid, in the engine's format (`--xt-grid`). Derived from [StatsBomb Open Data](https://github.com/statsbomb/open-data) |

## Running it

```sh
make fetch-data fetch-training   # the World Cup (test) and everything else (training)
make xt                          # about 10 s
make dataset                     # about 2 minutes
```

Checks: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest` (or `make lint test` from the root).
