# model

Offline modeling for the engine: what makes a goal likely, learnt from StatsBomb data the engine never sees live. Everything here reads the feeds `make export` writes (the simulator's broadcast, in the canonical schema), so what the model learns from is exactly what the engine sees.

The techniques, the results of each step and how to iterate on them are in [docs/MODEL.md](../docs/MODEL.md).

| Module | What |
| --- | --- |
| `model.xt` | Our own expected-threat (xT) grid: Karun Singh's Markov model, fitted on the training matches and compared with the published grid on the World Cup (`make xt`) |
| `model.dataset` | The goal model's rows: each team every 30 seconds from 15', with the engine's features (`engine.features`), whether it scores in the next 5 and 10 minutes, and whether it (and anyone) scores again before full time, into `data/model/{train,test}.npz` (`make dataset`) |
| `model.train` | The goal models, from a base rate to logistic regression (straight, and with a bent minute) and gradient-boosted trees: cross-validated by match on the training set, then scored once on the World Cup, with bootstrap intervals, reliability and alert lift (`make train`) |
| `model.rules` | The three rules retuned: each match replayed once to record what they see, then their settings re-run in numpy at the threshold giving 2 alerts a match, the best picked on the training set and scored once on the World Cup, and the engine checked to raise exactly the simulated alerts (`make rules`) |
| `model.fulltime` | The full-time models (another goal before the end of regulation, by the team and by anyone: what the markets' "over" lines pay on), with the expected minutes left from how long the competition's matches last; compared like `model.train`, also at the goal model's alerts, and the shipped one written into the engine (`engine/src/engine/detectors/fulltime_model.json`) after checking its arithmetic (`make fulltime`) |
| `model.export` | The shipped goal model: the curved logistic regression at 10', fitted on all the training data, its alert threshold picked out of fold, written as plain JSON into the engine (`engine/src/engine/detectors/goal_model.json`) after checking the engine's arithmetic matches scikit-learn's (`make export-model`) |

| Artifact | What |
| --- | --- |
| `artifacts/xt_statsbomb_12x8.json` | Our 12×8 xT grid, in the engine's format (`--xt-grid`). Derived from [StatsBomb Open Data](https://github.com/statsbomb/open-data) |

## Running it

```sh
make fetch-data fetch-training   # the World Cup (test) and everything else (training)
make xt                          # about 10 s
make dataset                     # about 2 minutes
make train                       # about 2 minutes; ARGS="--horizon 5" for 5'
make export-model                # about 15 s; then `make evaluate` to see its alerts
make fulltime                    # about 3 minutes
make rules                       # about 20 minutes; prints the rules' new defaults
```

Checks: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest` (or `make lint test` from the root).
