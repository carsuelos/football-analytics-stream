# Modeling

How the engine learns what makes a goal likely: the data, each technique, what it scored and how to iterate on it. The plan and checklist are in [PLAN.md](PLAN.md) (Phase 3).

## The question

The Phase 1 alerts describe the game: a team is pressing, a team has taken control. The question for Phase 3 is whether they **predict** goals: when the engine says a team is threatening, does it score more often than it would anyway?

Two numbers answer it, both measured on matches the model never trained on:

- **Lift**: how often the alerted team scores in the next 5 or 10 minutes, divided by how often a team scores in any 5 or 10 minutes. 1.0 is no better than chance.
- **Brier score**: the mean squared error of a probability, `mean((p - y)^2)` with `y` 1 for a goal and 0 otherwise. Lower is better. The **Brier skill score** is `1 - brier / brier_of_base_rate`: 0 is no better than always predicting the average, 1 is perfect, below 0 is worse than the average. With goals as rare as they are, a skill score of a few percent is already real information.

Also used: **log loss** (`-mean(y log p + (1 - y) log(1 - p))`, which punishes confident mistakes harder), **calibration** (the sum of the predictions over the number of goals: 1.0 means it predicts as many goals as happen) and, from PR 5 on, **AUC** (how often a random positive is ranked above a random negative: 0.5 is chance).

## Data

| Set | Matches | Goals | Used for |
| --- | ---: | ---: | --- |
| Test: 2022 World Cup (`make fetch-data`) | 64 | 172 | Every number in this document, unless it says otherwise. Never trained on |
| Training: every other men's senior StatsBomb season since 2003 (`make fetch-training`) | 2,552 | 7,214 | Fitting |

The training set is mostly club football: 1,517 matches from the 2015/16 Premier League, La Liga, Serie A and Ligue 1, about 520 Barcelona matches (the Messi data set), 115 from the Indian Super League, and 250 international tournament matches (World Cup 2018, Euro 2020 and 2024, Copa América 2024, AFCON 2023), the closest to the test set. See [PLAN.md](PLAN.md) for the full list and its biases.

Both sets go through the same path as live: the simulator exports each match exactly as it broadcasts it (`make export`, `simulator/cmd/export`), and the engine replays it offline (`engine.backtest`) through the pipeline, ticker and detectors it runs live. So a model fitted on the replays sees the canonical schema, not StatsBomb's, and moving to another provider means exporting that provider's data the same way.

## Baseline: the Phase 1 rules

`make evaluate`, all 64 World Cup matches, 157 goals after the 15' warm-up. A team scores in a given 5' of play 6.5% of the time, and in a given 10' 12.2%.

| Alert | Count | Scores in 5' | Lift | Scores in 10' | Lift |
| --- | ---: | ---: | ---: | ---: | ---: |
| momentum_shift | 330 | 5.5% | 0.8 | 12.4% | 1.0 |
| goal_threat | 209 | 9.1% | 1.4 | 14.8% | 1.2 |
| control_shift | 367 | 6.0% | 0.9 | 14.4% | 1.2 |
| all | 906 | 6.5% | 1.0 | 13.8% | 1.1 |

54% of goals had an alert for the scorer in the 10' before, but at 906 alerts in 64 matches (14 a match) that is mostly volume. The model has to beat a 10' lift of 1.1.

> **Fixed: ticks saw a few seconds ahead.** These numbers are after a fix found while training the model (step 3). The pipeline holds events back for up to 5 s in case one arrives late, then releases them together; it used to put the whole batch in the windows before the ticker looked at each event, so a tick could see events a few seconds after it, goals included. Now each event goes into the windows only as it is handed on (`Pipeline.handle_each`). Before the fix the rules looked slightly better (911 alerts, 10' lift 1.2); the model's features exposed it, as a goal a few seconds *after* the tick showed up in them.

## Step 1: our own xT grid

**Status: done (PR 3).** Code: [`model/src/model/xt.py`](../model/src/model/xt.py), run with `make xt`.

### Why

xT (expected threat) is behind two of the three metrics and the goal threat alert: every pass or carry adds `xT[end] - xT[start]`. Until now the engine used Karun Singh's published grid, fitted on Wyscout data from other leagues and downloaded at run time because it has no licence. Fitting our own grid on the training data checks the published one, puts the whole pipeline on data we can attribute, and gives us the method to refit when the data changes (a live provider, women's football, a different grid size).

### Technique: a Markov chain over pitch zones

The pitch is split into the engine's 12×8 grid (10 × 10 yards per zone). From each zone `z`, counted over every training match:

- `s[z]`: the share of the team's actions there that are shots (penalties excluded: they are set pieces, and they would make the penalty spot's zone worth 78%);
- `g[z]`: the share of those shots that score;
- `m[z] = 1 - s[z]`: the share that are moves (passes and carries, successful or not);
- `T[z, z']`: the share of moves from `z` that end in `z'` **and keep the ball**. A failed pass is counted as a move but goes nowhere, so the rows of `T` add up to the completion rate, and losing the ball is worth zero.

The value of having the ball in `z` is the chance of scoring before losing it:

```text
xT[z] = s[z] · g[z]  +  m[z] · Σ_z' T[z, z'] · xT[z']
         shoot now       move, then it's worth what the new zone is worth
```

It's a linear system, solved by iterating from `xT = 0`: after `k` iterations `xT[z]` is the chance of scoring within `k` actions. It converges in about 110 iterations (to 1e-10), in milliseconds; the time goes on counting 4.5 million passes and carries across 10 processes (about 6 s).

Two details:

- **Mirroring.** Left and right are the same to the model, so the counts are added to their mirror image across the length of the pitch before solving. This doubles the data in each zone, and makes the grid symmetric (the published grid is too).
- **Short carries.** A carry that stays in its zone is a move from `z` to `z`. It changes how many iterations the solve takes, not where it ends up, so carries are included as they are.

### Results

On 63,658 non-penalty shots (6,775 goals) and 4.5 million passes and carries:

```text
Ours (% chance of scoring before losing the ball; attacking left to right):
  0.3   0.4   0.6   0.7   0.8   1.0   1.2   1.5   1.9   2.3   2.5   3.3
  0.4   0.5   0.7   0.8   0.9   1.1   1.3   1.7   2.1   2.6   3.0   3.0
  0.5   0.6   0.7   0.8   1.0   1.2   1.4   1.7   2.2   3.0   4.8   4.9
  0.6   0.6   0.7   0.9   1.0   1.2   1.4   1.8   2.3   3.8  11.3  19.7
  0.6   0.6   0.7   0.9   1.0   1.2   1.4   1.8   2.3   3.8  11.3  19.7
  0.5   0.6   0.7   0.8   1.0   1.2   1.4   1.7   2.2   3.0   4.8   4.9
  0.4   0.5   0.7   0.8   0.9   1.1   1.3   1.7   2.1   2.6   3.0   3.0
  0.3   0.4   0.6   0.7   0.8   1.0   1.2   1.5   1.9   2.3   2.5   3.3

Published (Karun Singh):
  0.6   0.8   0.8   1.0   1.1   1.2   1.5   1.7   2.1   2.8   3.5   3.8
  0.8   0.9   0.9   1.1   1.2   1.4   1.6   1.9   2.4   3.0   4.1   4.6
  0.9   1.0   1.0   1.1   1.3   1.4   1.7   1.9   2.4   2.9   5.5   6.4
  0.9   1.1   1.0   1.1   1.3   1.5   1.7   2.0   2.4   3.5  10.8  25.7
  0.9   1.1   1.0   1.1   1.3   1.5   1.7   2.0   2.4   3.5  10.8  25.7
  0.9   1.0   1.0   1.1   1.3   1.4   1.7   1.9   2.4   2.9   5.5   6.4
  0.8   0.9   0.9   1.1   1.2   1.4   1.6   1.9   2.4   3.0   4.1   4.6
  0.6   0.8   0.8   1.0   1.1   1.2   1.5   1.7   2.1   2.8   3.5   3.8
```

The shapes agree (correlation 0.988): value climbs slowly through midfield and jumps in the box. Ours is about half a point lower almost everywhere, and 6 points lower in the zone right in front of goal (19.7% against 25.7%). The likely reasons are StatsBomb counting more actions than Wyscout (more carries, so each action is worth a bit less, but more of them), and the published grid including some set pieces.

**Scored on the World Cup.** For every pass, carry and non-penalty shot, is the grid's value of its zone a good forecast of whether that possession ends in a goal? 118,195 actions, 2.0% of them in possessions that scored:

| Actions | Grid | Brier | Skill | Log loss | Calibration |
| --- | --- | ---: | ---: | ---: | ---: |
| all | ours | 0.01957 | 0.012 | 0.0968 | 0.77 |
| all | published | 0.01957 | 0.012 | 0.0960 | 0.93 |
| final third | ours | 0.03144 | 0.025 | 0.1389 | 0.93 |
| final third | published | 0.03149 | 0.023 | 0.1394 | 1.07 |

- **They're equally good.** Same Brier score overall; ours is marginally better in the final third, where the engine's metrics mostly move, and the published grid in the team's own half, where both are close to zero.
- **Ours predicts too few goals overall** (calibration 0.77): World Cup possessions from deep scored more often than the club football it learnt from. Over the final third it's close (0.93).
- **Skill is small either way** (1–2.5%): where the ball is says a little about whether this possession scores. That's expected: xT is meant to value actions, and it's the sum of many of them over minutes that the metrics use.

**Effect on the alerts.** Swapping our grid into `make evaluate ARGS="--xt-grid ../model/artifacts/xt_statsbomb_12x8.json"`:

| Alert | Grid | Count | Lift 5' | Lift 10' |
| --- | --- | ---: | ---: | ---: |
| goal_threat | published | 209 | 1.4 | 1.2 |
| goal_threat | ours | 163 | 1.3 | 1.3 |
| all | published | 906 | 1.0 | 1.1 |
| all | ours | 860 | 1.0 | 1.1 |

The goal threat alert fires on xT added per minute over a threshold that was tuned with the published grid. Ours is lower, so it fires less; the alerts it keeps do slightly better (10' lift 1.3 against 1.2), though on about 160 alerts that is within noise. Momentum and control shift don't use xT's level, and are unchanged.

### Decision

Our grid is committed ([`model/artifacts/xt_statsbomb_12x8.json`](../model/artifacts/xt_statsbomb_12x8.json), derived from StatsBomb Open Data) and can be used with `--xt-grid`. The engine's default stays the published grid until the thresholds are retuned on the training data (step 5), so that switching the grid and the thresholds is measured together.

### Iterating

- Finer grids (16×12, 24×16) need more data per zone; the mirroring and the 2,552 matches make 16×12 plausible. The engine's grid size is a constant in `engine.metrics.pitch`.
- Refit on just international tournaments (250 matches) to see whether the calibration gap is about the competition.
- Action-based models (VAEP, or xT with pass direction) value the action, not just the zone, but need more than a lookup table at run time.

## Step 2: features and labels

**Status: done (PR 4).** Code: [`engine/src/engine/features.py`](../engine/src/engine/features.py) (the features) and [`model/src/model/dataset.py`](../model/src/model/dataset.py) (the rows), run with `make dataset` (about 2 minutes).

### The prediction

At each 30-second tick from 15' on, for each team: **will this team score in the next 5 minutes? In the next 10?** One row per team per tick, so a 90-minute match gives about 300 rows (more with extra time). The 15' warm-up and the tick are the rules' (Phase 1), so the model and the rules are scored on the same moments.

- **Labels** look only ahead: a goal at `g` labels the ticks `t` with `t < g ≤ t + horizon`. A goal at the tick itself is already in the features (the score), and not in the label.
- **The end of the match** cuts the horizon short: at 88' a team has only 2 minutes to score in, and is labelled as such. That's what the live question is too ("will they score before the end?"), and `minute` lets the model learn it.
- **Rows overlap**: consecutive ticks share 9.5 of their 10 minutes, so they are nearly copies. Every split of the data (cross-validation, bootstrap) is by match, never by row, or the model would be tested on near-copies of what it trained on.

### The features

43 numbers per row, from the team's point of view (`opp_` is the same for its opponent):

| Group | Features | Why |
| --- | --- | --- |
| Game state | `minute`, `extra_time`, `score_diff`, `goals_for`, `goals_against`, `since_goal_min` | Teams chasing a game attack more; goals are more frequent late on; a goal is followed by a kick-off and a reset |
| Last 5' and 10' (each) | `tilt`, `xt`, `pressure`, `shots`, `xg`, `box_entries`, `box_actions`, `recoveries`, and the opponent's | The Phase 1 metrics, plus the parts of the pressure index, so the model can weigh them itself instead of using the hand-set weights |
| Match so far | `xg_match`, `shots_match`, `xt_match` (each with the opponent's) and `tilt_match` | Which team is better on the day. There is no pre-match strength (odds, ratings) in the data, so this is the closest proxy |

All of them come from the canonical events the engine already has, through the engine's own metric functions: the live detector will call the same `FeatureTracker` at each tick. A live provider would need to send the same event types, with locations and an xG per shot.

**No peeking.** A test changes everything after 20' of a match and checks that no feature before 20' changes. The windows only hold events the engine has released, and the reorder buffer releases them in match-time order, so a feature can't see an event from after its tick.

### The data

| Set | Rows | Matches | Scores within 5' | Within 10' |
| --- | ---: | ---: | ---: | ---: |
| Training | 766,134 | 2,552 | 7.2% | 13.5% |
| Test (World Cup) | 20,592 | 64 | 6.5% | 12.1% |

The test rates match the rules' evaluation (6.5% and 12.2%). Club football in the training set scores a little more often than the World Cup did: a model that just learnt the training rate would over-predict on the test by about 10%.

### One feature at a time

Before any model: how well does each feature alone rank the rows (AUC for scoring within 10')? 0.5 is chance; below 0.5 means more of it goes with fewer goals, as for the opponent's features.

| Feature | Train AUC | Test AUC |
| --- | ---: | ---: |
| `tilt_match` | 0.608 | 0.590 |
| `tilt_10` | 0.580 | 0.587 |
| `pressure_10` | 0.575 | 0.584 |
| `xt_10` | 0.566 | 0.575 |
| `tilt_5` | 0.565 | 0.574 |
| `box_entries_10` | 0.565 | 0.563 |
| `pressure_5` | 0.560 | 0.560 |
| `opp_pressure_10` | 0.440 | 0.441 |
| `xt_match` | 0.558 | 0.559 |
| `opp_xt_match` | 0.443 | 0.419 |
| `xg_match` | 0.554 | 0.560 |
| `score_diff` | 0.550 | 0.543 |
| `xg_10` | 0.542 | 0.586 |
| `minute` | 0.484 | 0.494 |
| `since_goal_min` | 0.492 | 0.455 |
| `extra_time` | 0.499 | 0.499 |

(`make dataset` prints all 43.)

What this says:

- **Every signal is weak.** The best single feature is right about which of two rows scores 61% of the time, against 50% for a coin. That's football: goals are rare and noisy, and most of what decides them (a deflection, a save) isn't in the event data.
- **Who is better on the day beats what just happened.** Field tilt over the whole match ranks better than over the last 10', and 10' better than 5'. The short-term "momentum" the Phase 1 alerts look for is a weaker signal than which team has been on top for longer. That fits the rules' modest lift (about 1.1).
- **10' windows beat 5' ones** for every metric: more events, less noise.
- **The opponent matters as much as the team** (`opp_pressure_10` is 0.44, as far from 0.5 as `pressure_10`), so a model should look at both sides.
- **Train and test agree**: the club-trained ranking holds on the World Cup, so the training set is usable for it. `xg_10` is the exception, much better on the test (0.59) than in training (0.54); 64 matches is a small test, so differences of a few hundredths are within noise.

Combining weak, partly independent signals is what the models in the next step are for.

## Next steps

3. Models: base rate, logistic regression, gradient boosting.
4. A `goal_chance` alert from the model.
5. Retune the rule thresholds on the training data.
