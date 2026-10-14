# Modeling

How the engine learns what makes a goal likely: the data, each technique, what it scored and how to iterate on it. The plan and checklist are in [PLAN.md](PLAN.md) (Phase 3).

## The question

The Phase 1 alerts describe the game: a team is pressing, a team has taken control. The question for Phase 3 is whether they **predict** goals: when the engine says a team is threatening, does it score more often than it would anyway?

Two numbers answer it, both measured on matches the model never trained on:

- **Lift**: how often the alerted team scores in the next 5 or 10 minutes, divided by how often a team scores in any 5 or 10 minutes. 1.0 is no better than chance.
- **Brier score**: the mean squared error of a probability, `mean((p - y)^2)` with `y` 1 for a goal and 0 otherwise. Lower is better. The **Brier skill score** is `1 - brier / brier_of_base_rate`: 0 is no better than always predicting the average, 1 is perfect, below 0 is worse than the average. With goals as rare as they are, a skill score of a few percent is already real information.

Also used: **log loss** (`-mean(y log p + (1 - y) log(1 - p))`, which punishes confident mistakes harder), **calibration** (the sum of the predictions over the number of goals: 1.0 means it predicts as many goals as happen) and **AUC** (how often a random positive is ranked above a random negative: 0.5 is chance).

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

**No peeking.** A test changes everything after 20' of a match and checks that no feature before 20' changes. The windows only hold events the engine has released, in match-time order. That turned out not to be enough: the reorder buffer releases events in batches, and the whole batch used to reach the windows before the tick at its first event was taken, so a tick could see a few seconds ahead. Step 3 found it (a goal leaked into the features); since the fix, events reach the windows one at a time, and a dataset test checks that the tick just before a goal doesn't see it.

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

## Step 3: models

**Status: done (PR 5).** Code: [`model/src/model/train.py`](../model/src/model/train.py), run with `make train` (about 2.5 minutes). It prints everything below and writes it to `data/model/results.json`. `make train ARGS="--horizon 5"` runs the 5' version.

### The setup

Every model gets the same 43 features and predicts the same thing: the probability that this team scores in the next 10 minutes. Within 10', a team scores in 13.5% of the training rows (766,134 rows) and 12.1% of the test rows (20,592).

Five models, from simplest to most flexible. Each one has to beat the one before it to be worth its complexity.

| Model | What it is | Settings tried |
| --- | --- | --- |
| **base rate** | Always predicts the training average (13.5%). The floor: the skill score is measured against it | none |
| **game state** | Logistic regression on just `minute`, `extra_time`, `score_diff`, `goals_for`, `goals_against`, `since_goal_min`. Answers "how much do the events add on top of the clock and the score?" | C = 1 |
| **logistic** | Logistic regression on all 43 features | C = 0.001, 0.01, 1 |
| **curved** | The logistic regression, plus a bent line for the minute (see below) | C = 0.001, 0.01 |
| **boosted** | Gradient-boosted trees on all 43 features | 100 trees × 4 leaves, 150 × 8, 300 × 8 |

### Techniques

**Logistic regression.** The model adds up the features, each times a weight, and squashes the sum into a probability: `p = 1 / (1 + exp(-(b + w1·x1 + w2·x2 + …)))`. The sum is the **log-odds** (`log(p / (1 - p))`); a weight says how much one unit of a feature moves it. Training picks the weights that make the observed goals most likely (it minimizes log loss). It can only learn straight-line effects: each feature pushes the log-odds the same amount per unit everywhere.

- **Standardization.** Before fitting, each feature has its training mean subtracted and is divided by its standard deviation (scikit-learn's `StandardScaler`). Then all features are on the same scale and the weights are comparable: a weight is "log-odds per standard deviation". It also makes the fit converge.
- **L2 regularization.** The fit is penalized for large weights (`C` is the inverse strength: small C, strong penalty). With correlated features (`xt_5`, `xt_10`, `xt_match`), it stops the model from giving one a large positive weight and another a large negative one to cancel out. Here C made no difference (0.001 to 1 all scored 0.1140): 766,000 rows are plenty for 43 weights.

**Hinges (a linear spline).** The chance of scoring isn't a straight line in the minute: flat for most of the match, then it collapses at full time because the 10 minutes run past the end. A straight line can't do that. The curved model adds, for each **knot** `k` (60, 80, 85, 90, 95, 100), a feature `max(0, minute - k)`: zero before the knot, then rising. Each gets its own weight, so the slope can change at each knot, and the minute's effect becomes a line with bends. It is still a logistic regression (the hinges are just more columns), so it stays simple to run in the engine: no library, a few lines of Python. A smooth spline (`SplineTransformer`) scored the same (CV AUC 0.628 vs 0.629).

**Gradient-boosted trees** (scikit-learn's `HistGradientBoostingClassifier`). A sequence of small decision trees, each fitting what the trees before it got wrong. Trees find curves and interactions (a feature mattering more late in the match) by themselves, which logistic regression can't. The cost is that they overfit easily and are harder to read and to ship. Settings: learning rate 0.05, at least 500 rows per leaf (so a leaf is never a handful of near-identical ticks from one match), and small trees.

**Cross-validation by match** (`GroupKFold`, 5 folds). The training matches are split into 5 groups; each model is fit on 4 and scored on the 5th, five times, so every training row gets an **out-of-fold** prediction from a model that didn't see its match. Splitting by match matters: consecutive ticks are near-copies (they share 9.5 of 10 minutes), so a random row split would score the model on copies of its training rows. The settings with the best out-of-fold log loss are picked, refit on all 2,552 matches, and only then scored on the World Cup, once.

**Bootstrap intervals.** 64 test matches is not much. To see how much a number could move by chance, the test matches are resampled with replacement 1,000 times (a resample might have Argentina–France twice and no Japan–Spain), the number is recomputed on each, and the middle 95% is the interval. If an interval for "better than X" includes 0, the test can't tell the two apart.

**Alerts from probabilities.** A model gives a probability for every team at every tick; an alert is when it crosses a threshold. The threshold is set for a number of **alerts a match**, on the out-of-fold training predictions (never on the test set), with the rules' 5' cooldown per team: 14.2 a match (the rules' volume), 5 and 2. The test set then gets the same lift measure as the rules.

### Results

Cross-validation on the 2,552 training matches, and the 64 World Cup matches:

| Model | CV skill | CV log loss | CV AUC | Test skill | Test log loss | Test AUC | Test calibration |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| base rate | 0 | 0.3951 | 0.50 | −0.002 | 0.3697 | 0.50 | 1.11 |
| game state | 0.005 | 0.3925 | 0.555 | 0.003 | 0.3680 | 0.541 | 1.08 |
| logistic | 0.021 | 0.3849 | 0.618 | 0.015 | 0.3626 | 0.599 | 1.04 |
| **curved** | **0.026** | **0.3824** | **0.629** | **0.021** | 0.3622 | **0.616** | **0.99** |
| boosted (100 × 4) | 0.025 | 0.3829 | 0.627 | 0.019 | **0.3611** | 0.611 | 1.03 |

95% bootstrap intervals on the test set: curved skill −0.002 to 0.042 and AUC 0.565 to 0.668; boosted AUC 0.562 to 0.662. Against plain logistic, the curved model's Brier gain is −0.004 to +0.015: on 64 matches, the test alone can't separate them. The cross-validation, on 40 times as many matches, can, and every model ranks the same on both.

What it says:

- **The events add real information.** The clock and the score alone (game state) barely beat the average (skill 0.005). Adding the events quadruples it (0.021).
- **It's weak information.** A skill of 2–3% and an AUC of 0.62 mean the model is right about *which* moments are more dangerous a bit more often than not, not that it sees goals coming. That is the nature of football: most goals come from moments that look like many others that didn't produce one. Pre-match strength (odds, ratings) would likely add the most, and the data doesn't have it.
- **Bigger trees did worse** (CV skill 0.025 → 0.024 → 0.023 as the trees grow). There isn't enough signal for complex interactions; they fit noise.
- **The trees' edge over logistic was the minute.** Their permutation importance (how much the test log loss rises when one feature is shuffled) puts `tilt_match` (0.0068) and `minute` (0.0066) far ahead of everything else (`xt_match` 0.0007, `xt_10` 0.0006, `score_diff` 0.0005). Once logistic regression gets a bent line for the minute, it matches the trees: the curved model is a little better on CV, AUC and calibration, the trees a little better on test log loss, all within noise.
- **Calibration is good.** Reliability (test rows grouped by predicted probability) for the curved model: predicted 9.5% → 9.2% scored, 12.5% → 10.8%, 15.9% → 15.2%, 19.7% → 18.2%, 24.0% → 22.0%, 29.9% → 35.0%. The exception is the lowest group: predicted 3.0%, 6.7% scored. Those are the last minutes of matches, and the 2022 World Cup added unusually long stoppage time, so more of its goals came after the point where club matches would be over.

**What the curved model learned** (log-odds per standard deviation, largest first): `tilt_match` +0.25, `xt_match` +0.14, `opp_pressure_10` −0.10, `xg_match` +0.08, `pressure_10` +0.07, `extra_time` +0.07, and the minute through the hinges. The minute's own effect, from 15': flat to 60' (−0.08), −0.25 at 80', −0.76 at 90', −1.77 at 95', −2.2 from 100'. "Minute" is continuous play time, including first-half stoppage time, so the second half ends at about 95.

So: **the team that has had the ball in the final third and moved it into dangerous zones all match is more likely to score next**, recent pressure adds a bit on top, and the opponent's recent pressure counts against. Recent shots and xG add little once the match-long numbers are in.

### Alerts: does it beat the rules?

Test set, thresholds set on the training data, 5' cooldown:

| Model | Alerts a match | Threshold | Alerts | Scores in 5' | Lift 5' | Scores in 10' | Lift 10' | 95% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| rules (baseline) | 14.2 | | 906 | 6.5% | 1.0 | 13.8% | 1.1 | |
| game state | 14.2 | 0.137 | 916 | 7.2% | 1.1 | 13.1% | 1.08 | 0.89–1.27 |
| logistic | 14.2 | 0.137 | 862 | 8.9% | 1.37 | 16.4% | 1.35 | 1.15–1.55 |
| curved | 14.2 | 0.138 | 811 | 8.9% | 1.36 | 16.6% | 1.38 | 1.19–1.57 |
| boosted | 14.2 | 0.136 | 856 | 9.2% | 1.42 | 16.8% | 1.39 | 1.21–1.57 |
| logistic | 5 | 0.191 | 262 | 11.1% | 1.70 | 20.2% | 1.67 | 1.19–2.21 |
| **curved** | **5** | **0.195** | **257** | **12.5%** | **1.91** | **22.2%** | **1.83** | **1.39–2.35** |
| boosted | 5 | 0.191 | 266 | 10.9% | 1.68 | 21.4% | 1.77 | 1.23–2.34 |
| logistic | 2 | 0.231 | 107 | 13.1% | 2.01 | 24.3% | 2.01 | 1.20–2.89 |
| curved | 2 | 0.237 | 87 | 11.5% | 1.77 | 26.4% | 2.19 | 1.21–3.18 |
| boosted | 2 | 0.227 | 99 | 11.1% | 1.71 | 22.2% | 1.84 | 0.96–2.75 |

- **At the rules' volume, every model beats them**: 10' lift 1.38 for the curved model, and the bottom of its interval (1.19) is above the rules' 1.1.
- **Fewer alerts, stronger alerts.** At 5 a match, the alerted team scores within 10' 22% of the time, 1.8 times the usual rate. At 2 a match the lift rises again, but on fewer than 100 alerts the interval is wide.
- **Game state alone doesn't beat the rules**: the events are what make the alerts work.

### The 5-minute horizon

The same models predicting the next 5' (`--horizon 5`; base rate 7.2% train, 6.5% test) rank the same way (CV skill: curved 0.013, boosted 0.0125, logistic 0.012; test: curved 0.012, AUC 0.607, calibration 1.00), and their alerts are no better: curved at 5 a match has a 10' lift of 1.72 (vs 1.83) and a 5' lift of 1.76 (vs 1.91). Shorter horizons have half as many goals to learn from. The 10' model is the one to use.

### The leak, and how it was found

The first run had the boosted trees far ahead: a top group predicted at 72% that scored 84% of the time, and alerts with a lift of 6.5. Football isn't that predictable, so the rows behind it were inspected: `since_goal_min` was negative (−0.03 to −0.07 minutes), so features at a tick already counted a goal scored a few seconds later. The trees had learned "a goal was just scored by this team, and the score hasn't caught up", which predicts the label perfectly.

The cause was in the engine, not the model: the reorder buffer released events in batches, and the whole batch went into the windows before the ticks inside it were taken (see the note in the baseline). The fix (PR #25) applies to the live engine, the replay and the dataset alike, and tests in the engine and the dataset check it. Every number in this document is after the fix.

The lesson for iterating: **when a model is much better than it should be, look for a leak before celebrating.** Trees are good at finding them; it's worth training them even when the plan is to ship logistic regression, as a check.

### Decision

The engine will use the **curved logistic regression**: the best cross-validated model on every measure, well calibrated, and the simplest to run. What it needs at run time fits in a small JSON file (the feature names, knots, means, scales, weights and intercept), and running it is a dot product. No scikit-learn in the engine, no pickled model, and anyone can read the weights. The default operating point will be about **5 alerts a match** (threshold about 0.195, against a base rate of 13%), set in step 4.

### Iterating

Ideas, roughly by expected value:

- **A clock relative to the period.** `minute` mixes "how far into the match" with "how much is left", and stoppage time varies (the 2022 World Cup's was unusually long, which is where calibration is worst). Minutes since the period started and an indicator for stoppage time, or the announced added time from a live provider, would separate them.
- **Team strength.** Pre-match odds or Elo ratings say who the better team is before a ball is kicked. `tilt_match` and `xt_match` are standing in for them now. Club Elo or international Elo ratings by date could be joined on team names.
- **Red cards.** A sending-off changes everything, and the canonical schema has no card events yet. Adding them (schema, simulator, engine) would let the model use them.
- **Train closer to the test.** The training set is mostly club football with a higher goal rate (13.5% vs 12.1%). Weighting the 250 international tournament matches more, or recalibrating on them, could fix the overall calibration (1.11 for the base rate on the test).
- **Our xT grid.** The features use the published grid. Switching to ours (`--xt-grid`) means `make dataset` then `make train` again.
- **Interactions.** Hinges on the minute fixed the main curve. Products like `pressure_10 × minute>80` would let the model weigh late pressure differently; the trees don't suggest they matter much.
- **Sequence models** (an RNN or transformer over the raw events) only make sense if they beat the curved model on the same CV by more than noise; the trees not beating it is a hint they won't, at much higher cost.

To compare an idea: change the features or the model, run `make dataset` (if features changed) and `make train`, and compare the CV log loss and skill first (most data), then test AUC and the alert lift at 5 a match. A change worth keeping should improve CV by more than the gap between the settings tried (about 0.0005 in skill).

## Step 4: the model in the engine

The curved model now runs live as a fourth detector, `goal_chance`, next to the three rules.

### Shipping it: `make export-model`

`model.export` fits the curved model (10', C = 0.01, knots at 60/80/85/90/95/100) on **all** 2,552 training matches and writes `engine/src/engine/detectors/goal_model.json` (5 KB):

| Field | What |
| --- | --- |
| `features`, `minute_knots` | The 43 feature names in order, and the knots of the 6 hinge terms (`max(0, minute − k)`) appended after them |
| `mean`, `scale` | The standardization of each of the 49 terms |
| `coef`, `intercept` | The weights, in log-odds per standard deviation |
| `threshold`, `alerts_per_match` | The alert threshold (0.195) and the volume it was picked for (5 a match) |
| `base_rate`, `horizon_min`, `warmup_s` | 13.5% of training rows score within 10'; predictions start at 15' |
| `xt_grid`, `xt_grid_sha256` | The xT grid the features were computed with, and its digest |
| `training`, `test` | Cross-validated and World Cup scores, for the record |

Three details matter:

- **The threshold comes from cross-validation, not the final fit.** The model is fitted 5 times by match (GroupKFold) and each fold scores the matches it didn't see; the threshold is the score giving 5 alerts a match, after the 5' cooldown, on those out-of-fold scores. A threshold picked on the model's own training predictions would be a little too high, since a model is more confident on rows it has seen.
- **The engine doesn't run scikit-learn.** At run time a prediction is `sigmoid(intercept + Σ coef × (term − mean) / scale)`, a few lines of Python in `GoalModel.probability`. The export checks that the engine's `GoalModel`, loaded from the JSON it just wrote, gives the same probabilities as the scikit-learn pipeline on every training row (largest gap ≤ 1e-9), and refuses to write otherwise. Plain JSON instead of a pickle means no version coupling with scikit-learn, nothing executable in the artifact, and weights anyone can read.
- **The features must be computed the same way.** Training and the engine both use `engine.features.FeatureTracker`, and `GoalModel` refuses to load if the feature names or order differ from the engine's. The xT grid can't be checked that way, so the engine compares the grid it was given (`--xt-grid`) with the model's `xt_grid_sha256` and logs a warning if they differ: the model still runs, but its xT features are on a different scale than it learned.

### The detector

`GoalChance` (`engine/src/engine/detectors/goal_chance.py`) keeps its own `FeatureTracker`, fed every tick (every 30s of play), and from 15' it predicts each team's chance of scoring in the next 10'. Above the threshold it raises an alert, which goes through the same 5' cooldown per team as the rules (the cooldown the threshold was picked with). The alert carries:

- `value`: the probability, and `threshold`: 0.195; `window_s`: 600 (the horizon);
- `features`: the base rate and the raw values of up to 3 **drivers**, the terms that pushed this prediction up the most (coefficient × standardized value, positive). The minute, its hinges and the score are left out, since "it's the 30th minute" isn't a reason anyone can act on;
- a message such as, from the 2022 final: *"Argentina: 21% chance to score in the next 10' (usually 13%): high field tilt (match), low opponent's pressure (last 10'), high pressure (last 10')"*. High and low are relative to the training average.

The dashboard shows them as "Goal chance (model)"; the notifier and Kafka sinks pass them on like any other alert. `--no-goal-model` turns it off, and `--goal-model PATH` loads another model (both on `engine` and `python -m engine.backtest`).

### Results

`make evaluate` replays the World Cup through the engine itself (its pipeline, ticks and detectors, not the training code), so this checks that the shipped detector behaves like the model scored in step 3:

| Alerts | Count | A match | Scores in 5' | Lift | Scores in 10' | Lift | Opponent scores in 10' | Right after the team scored |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `goal_chance` | 257 | 4.0 | 12.5% | 1.9 | 22.2% | 1.8 | 10.1% | 15.2% |
| the 3 rules | 906 | 14.2 | 6.5% | 1.0 | 13.8% | 1.1 | | |
| all | 1,163 | 18.2 | 7.8% | 1.2 | 15.6% | 1.3 | | |

- **The engine reproduces training exactly**: 257 alerts with the same lifts as the curved model at 5 a match in step 3. (It's 4.0 a match on the World Cup, not 5: the test set has fewer goals and the threshold was set on club football.)
- **Each alert is worth much more than a rule alert**: the team scores within 10' 22% of the time, against 14% for a rule alert and 12% on average.
- **Coverage is the trade-off.** 28% of World Cup goals had a `goal_chance` alert for the scoring team in the 10' before, against 54% for the rules (with 3.5 times the alerts) and 69% for both. A lower threshold buys coverage at the cost of lift (step 3's table at 14.2 a match: 1.38).
- **15% of its alerts come within 5' of the same team scoring**, like the one in the final above (1.5' after Argentina's second goal). They're still predictions about the next 10', not reports of the goal: a team that has just scored usually has the tilt and xT that made it score. Whether to suppress them is a product decision; the model says the chance really is above average.

### Iterating

- **The operating point** is a single number: change `ALERTS_PER_MATCH` in `model/export.py` and `make export-model`. Step 3's table shows what to expect at 2 and 14 a match.
- **A new model** only has to produce the same JSON: anything that's a logistic regression over the engine's features, with or without hinges. A different model family (trees) would need its own detector class, and its own parity check.
- **New features** go into `engine/features.py` (so the engine serves exactly what training saw), then `make dataset train export-model`.

## Next steps

5. Retune the rule thresholds on the training data, and the final scorecard.
