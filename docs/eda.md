# EDA findings: what predicts a college hockey win

The conclusions of the 2025-26 EDA, and the feature set it hands to the model. The plan and
rules are in [eda_plan.md](eda_plan.md). The work is in `notebooks/01`–`08`. This document
holds conclusions only: CHN data stays out of the repo.

## The model in one line

**Home win probability = logistic(close-game shot share + goal differential + home ice
switch),** using each team's season to date, home minus away.

| Input | Definition | Why it's in |
|---|---|---|
| Close-game shot share | Share of shots on goal in periods that started tied or within one goal | The strongest predictor by far. It reflects skill (step 4: r = 0.81 between halves of a season) |
| Goal differential per game, no empty-net goals | (Goals for − empty-net goals − goals against) ÷ games | Adds a small, consistent amount on top of shots |
| Home ice switch | 1 = home game, 0 = neutral site, multiplying the home edge | An evenly matched home team wins about 53–54%. At a neutral site it's exactly 50/50 by rule |

**Model settings:**
- L2-regularized logistic regression, C = 1, with no separate intercept.
- The stat features are scaled to unit spread but not centered, so 0 still means "evenly
  matched".
- Training data: D-I vs D-I games only, ties dropped, and both teams must have played at
  least 3 games.

## How well it predicts

On the held-back end of 2025-26 (the last 159 games, including the conference and NCAA
tournaments):

| | Log loss | Brier | AUC | Accuracy |
|---|---|---|---|---|
| Always the home win rate | 0.675 | 0.241 | 0.500 | 64.8% |
| Win % only | 0.639 | 0.224 | 0.615 | 64.2% |
| **This model** | **0.627** | **0.219** | **0.639** | **66.7%** |

- **Calibration is good in the middle and a little cautious at the extremes:** strong
  favorites won slightly more often than predicted.
- **Accuracy is limited.** College hockey games are close to coin flips more often than
  they look, so the value of the model is honest probabilities, not confident picks.
- **The final test is 2026-27,** which hasn't been touched yet.

## What the EDA found, step by step

1. **Validation setup:** time-ordered 5-fold cross-validation (`TimeSeriesSplit`, k = 5).
   Features were chosen on folds 1–4 and confirmed once on fold 5. k = 5 was chosen because
   the feature ranking was identical at k = 3–5, and 5 leaves the most folds for choosing.
2. **Data checks:**
   - The data is complete and consistent.
   - Games against non-D-I teams are excluded, because CHN records those teams only
     partly.
   - 6.9% of games are ties, including shootouts, and they're dropped from the target.
3. **What wins a game, from inside it:**
   - Special teams and shot share go with winning. Discipline barely does.
   - Leading teams get outshot late in games (score effects).
4. **Skill vs. luck:**
   - **Stable:** shot-based stats and goal differential are readable within 4–8 games.
   - **Need a full season:** special teams, save % and discipline.
   - **Luck:** shooting %, PDO and record in one-goal games.
5. **Pre-game predictors:**
   - The season-to-date value beats recent form (last 3, 5 or 10 games, or a weighted
     recent average) for every stat.
   - Shot share is the best single predictor.
   - Goal differential beats win %.
   - The special teams index beats PP% or PK% alone.
   - Team save % beats the likely starter's save %.
6. **Game context:** once team strength is known, home vs. neutral site, rest days,
   back-to-backs and who won the first game of a series add nothing measurable. Home ice is
   real but small, and it's handled by the switch.
7. **Combined model:** only goal differential adds anything on top of shot share (+0.0014
   in log loss, better in 4 of 4 folds). Special teams, save %, streak, schedule strength and
   recent form don't.
   - **A minimum gain of 0.001 per feature group** was added after the first run. That run
     kept % scoring first on a gain of +0.0001, which is noise.
   - The minimum is applied to every group and changes only that one decision.
   - The first run's three-feature model scored 0.626 on the held-back games, against 0.627
     for this model. The difference is within noise, so the simpler model is kept.

## What didn't make it, and why

| Candidate | Reason |
|---|---|
| Recent form (last 3/5/10, weighted) | Worse than the season figure alone, and makes the combined model worse |
| Special teams (PP%, PK%, index) | Decide individual games, but barely repeat from game to game. They add nothing on top of shots |
| Save % (team or likely starter) | About half luck. The starter version is noisier than the team version |
| Shooting %, PDO, one-goal game record | Luck: they don't repeat from one half of the season to the other |
| Discipline (PIM, times shorthanded) | Doesn't predict results |
| % of games scoring first | Below the 0.001 minimum gain. A noisier copy of goal differential, and only partly skill |
| Win %, raw shot share, raw goal differential | Noisier copies of features already in the model |
| Strength of schedule, schedule-adjusted goal differential | A gain of +0.0016, but only in 2 of 4 folds. **First to revisit** |
| Rest, back-to-backs, series game 1 result | Nothing beyond team strength |
| Streak, form vs. season | Weak alone, nothing in combination |

## Known limits and next steps

- **One season.** About 1,000 games limit how much the model can learn. Effects smaller than
  about 0.002 in log loss can't be told apart from noise.
- **Early season:**
  - Teams have no history in their first games, and the warm-up rule skips games until both
    teams have 3 games.
  - **Next improvement:** a preseason rating carried over from the previous season (for
    example, Elo regressed toward the mean). It can only be tested once there's a second
    season to train on.
- **Neutral sites** are treated as exactly 50/50 home edge. A tournament that's close to
  one team's campus isn't modeled.
- **Calibration:**
  - The 50–60% bin ran about 8 points under the actual win rate.
  - Predictions over 80% were won 94% of the time (36 games).
  - Recheck on 2026-27 before correcting anything.
