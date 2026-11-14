# Model card: win_model_v1

The model behind the Win probability, Rankings and Model record tabs. How it was chosen:
[eda.md](eda.md). How it was trained and tested: `notebooks/09_model.ipynb`.

## What it does

It gives **the home team's chance of winning a D-I men's college hockey game**, from each
team's season so far.

- **The chance is for a decided game.** About 7% of games end tied (shootouts count as
  ties); those were left out of training.
- **At a neutral site there's no home edge.** Two evenly matched teams are 50/50.
- **Every team also gets one neutral-site rating.** The Rankings tab sorts by it, and it
  agrees with every neutral-site prediction.

**Intended use:** personal scouting and curiosity (BU's next opponent, any matchup, a model
poll). **Not for betting**, and not for anything shared: the data is College Hockey News's,
for personal, non-commercial use only.

## Inputs

All inputs use each team's **D-I games this season before the game's date**, home team
minus away team.

| Input | Definition | Weight |
|---|---|---|
| Close-game shot share | Share of shots on goal in periods that started tied or within one goal | 1.97× the odds per SD (SD 0.084) |
| Goal differential per game | (Goals for − empty-net goals − goals against) ÷ games | 1.24× the odds per SD (SD 1.71) |
| Home ice switch | 1 = home game, 0 = neutral site | An evenly matched home team wins 55.1% |

**Model:**
- L2-regularized logistic regression, C = 1, with no separate intercept: the home edge is
  multiplied by the switch.
- The stat inputs are scaled by their spread but not centered, so 0 still means "evenly
  matched".
- **The file that's actually used:** [models/win_model_v1.json](../models/win_model_v1.json)
  holds the coefficients, scales and the fingerprint of the frozen file.
- **The live code:** `src/models/win_model.py` applies the card. Notebook 09 checks it
  reproduces the frozen model exactly (largest probability difference about 2e-16).

## Training data

**2025-26:** 957 games. D-I vs D-I games only, ties dropped, and both teams had played at
least 3 games (the warm-up).

**How the features were chosen:** forward selection on time-ordered folds
(`TimeSeriesSplit`, k = 5), with rules fixed before each step.
- A feature group was kept only if it improved log loss by at least 0.001 and did so in at
  least 3 of 4 folds.
- **Rejected:** recent form (last 3, 5 or 10 games), special teams, save %, schedule
  strength, rest and back-to-backs. They added nothing on top of these two inputs.

## How well it does

| Test | Games | Log loss | AUC | Accuracy | Baseline log loss |
|---|---|---|---|---|---|
| 2025-26 held-back fold (Feb 21 – Apr 11, incl. tournaments) | 159 | 0.627 | 0.639 | 66.7% | 0.639 (win % only) |
| **2026-27, never seen before** (through Nov 13) | **173** | **0.643** | **0.672** | **63.6%** | 0.680 (home rate) |
| 2026-27 including the warm-up weeks (prediction log) | 283 | 0.666 | — | 64% | 0.680 (home ice only) |

- **It beats both simple baselines:** always picking the home rate, and "the better record
  wins". The 2026-27 edge over the home rate is +0.037 in log loss (95% interval −0.028 to
  +0.097). That's positive, but not yet statistically settled with 173 games.
- **Calibration:** good in the middle. 65–80% favorites have so far won less than predicted,
  but those groups are 30–40 games each.
- **College hockey is hard to call.** Expect honest probabilities, not confident picks.
- **Live record:** the Model record tab, from the prediction log. Rerunning notebook 09 adds
  games to the formal test and a line to the card.

## Limits

- **Early season:**
  - Teams with fewer than 3 games are below the warm-up. Those predictions are flagged
    "rough guide" and are overconfident.
  - Rankings need 5 games.
  - The fix is model v2 (last season carried over), planned for 2027-28 (see
    [eda.md](eda.md)).
- **Not adjusted for strength of schedule.** A team that piled up stats against weak
  opponents rates too high.
- **Neutral sites are treated as exactly neutral.** A tournament close to one team's campus
  isn't modeled.
- **Nothing about players.** Injuries, a hot goalie or lineup changes are invisible to it.
- **One season of training data** (about 1,000 games). Effects smaller than about 0.002 in
  log loss can't be told apart from noise.

## Changing it

**v1 never changes.** The rules for any change:
- **A new model is a new version** (`win_model_v2`), with its own card. v1's frozen file is
  never overwritten.
- **Every choice is made on training data only.**
- **It's tested on games it has never seen.**
- **It's logged next to v1 for a season,** so the comparison is like for like.
