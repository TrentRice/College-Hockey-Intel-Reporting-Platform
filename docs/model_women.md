# Model card: win_model_women_v1

The women's win model, behind the Win probability, Rankings and Model record tabs when the
site is switched to women's. How it was chosen: [eda_women.md](eda_women.md). How it was
trained and tested: `notebooks/women/09_model.ipynb`. The men's model has its own card,
[model.md](model.md).

## What it does

It gives **the home team's chance of winning a D-I women's college hockey game**, from each
team's season so far.

- **The chance is for a decided game.** About 6% of games end tied (shootouts count as
  ties); those were left out of training.
- **At a neutral site there's no home edge.** Two evenly matched teams are 50/50.
- **Every team also gets one neutral-site rating,** which the Rankings tab sorts by.

**Intended use:** scouting and curiosity (BU's next opponent, any matchup, a model poll). Not
for betting. The data is College Hockey News's, shown with their permission.

## Inputs

All inputs use each team's **D-I games this season before the game's date** (complete box
scores only), home team minus away team.

| Input | Definition | Weight |
|---|---|---|
| Shots for per game | Shots on goal ÷ games | 2.75× the odds per SD (SD 9.2 shots per game) |
| Schedule-adjusted goal differential | Goals for − goals against, per game, + the average pre-game goal differential per game of the opponents faced so far | 2.27× the odds per SD (SD 2.1 goals per game) |
| PDO | Shooting % (no empty-net goals) + save % | **0.71×** the odds per SD (SD 0.040): a higher PDO *lowers* the chance, holding the other two fixed |
| Home ice switch | 1 = home game, 0 = neutral site | An evenly matched home team wins 51.9% |

**Why PDO's weight is negative:** on its own, a higher PDO goes with winning. But once goal
differential is known, a high PDO means part of that differential came from hot shooting or
goaltending, which repeats only partly (r = 0.42 between halves of a season). The model
discounts it and leans on the shots.

**Model:**
- L2-regularized logistic regression, C = 1, no separate intercept: the home edge is
  multiplied by the switch.
- The stat inputs are scaled by their spread but not centered, so 0 means "evenly matched".
- **The file that's used:** [models/win_model_women_v1.json](../models/win_model_women_v1.json)
  holds the coefficients, scales and the fingerprint of the frozen file.
- **The live code** that applies the card is built in Phase 3. Notebook 09 then checks it
  reproduces the frozen model exactly, as it does for the men's; until that check passes,
  nothing from this model appears on the site.

## Training data

**2025-26:** 579 games. D-I vs D-I games (D-I *that season*: four programs moved up in
2026-27), complete box scores only (two incomplete CHN pages excluded), ties dropped, and both
teams had played at least 3 games.

**How the features were chosen:** forward selection on time-ordered folds (`TimeSeriesSplit`,
k = 4), with rules fixed before each step ([eda_plan_women.md](eda_plan_women.md)). A feature
group was kept only if it improved log loss by at least 0.0013 and did so in at least 2 of 3
folds. Rejected: recent form, special teams, save % and shooting % alone, 3rd-period goal
differential, streak, discipline, rest and back-to-backs.

## How well it does

| Test | Games | Log loss | AUC | Accuracy | Baseline log loss |
|---|---|---|---|---|---|
| 2025-26 held-back fold (Feb 7 – Mar 22, incl. tournaments) | 115 | 0.541 | 0.781 | 73.9% | 0.567 (win % only) |
| **2026-27, never seen before** (through Nov 24) | **244** | **0.627** | **0.753** | **70.1%** | 0.621 (win % only), 0.695 (home rate) |

**By how many games the less experienced team had played (2026-27):**

| | Games | Log loss | Home-rate log loss | Accuracy |
|---|---|---|---|---|
| 3–5 games | 65 | 0.837 | 0.704 | 58.5% |
| 6–8 games | 67 | 0.546 | 0.691 | 79.1% |
| 9+ games | 112 | 0.553 | 0.692 | 71.4% |

- **From 6 games on, it's strong:** log loss about 0.55 against 0.69 for the home rate.
- **Overall it ties "the better record wins" so far** (log loss −0.006, 95% interval −0.071 to
  +0.054) while ranking games better (AUC 0.753 vs 0.723). The early-season games pull it
  down.
- **Calibration:** overconfident at the extremes on 2026-27 so far (its 88% picks won 78%, its
  16% picks 23%), mostly from the early weeks.
- **Live record:** the Model record tab, once the women's prediction log starts (Phase 3).
  Rerunning notebook 09 adds a line to the card's `test_runs`.

## Limits

- **Early season:** overconfident until teams have about 6 games. **The site labels women's
  predictions a rough guide until both teams have 6 games** (the men's threshold is 3). The
  fix is women's v2 (last season carried over), planned for 2027-28 (see
  [eda_women.md](eda_women.md)).
- **Neutral sites are treated as exactly neutral** (30 neutral-site games in training).
- **Nothing about players:** injuries, a hot goalie or lineup changes are invisible to it.
- **One season of training data** (579 games). Effects smaller than about 0.003 in log loss
  can't be told apart from noise.

## Changing it

**v1 never changes.** A new model is a new version (`win_model_women_v2`) with its own card;
every choice is made on training data only, tested on games it has never seen, and logged next
to v1 for a season.
