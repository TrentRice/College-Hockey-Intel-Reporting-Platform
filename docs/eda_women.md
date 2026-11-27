# EDA findings: what predicts a women's college hockey win

The conclusions of the women's 2025-26 EDA, and the feature set it hands to the model. The
rules, written before any result was seen, are in [eda_plan_women.md](eda_plan_women.md). The
work, with every table and chart, is in `notebooks/women/01`–`09`. The men's version is
[eda.md](eda.md); the women's was built from scratch, not copied from it.

## The model in one line

**Home win probability = logistic(shots for per game + schedule-adjusted goal differential
+ PDO + home ice switch),** using each team's season to date, home minus away.

| Input | Definition | Why it's in |
|---|---|---|
| Shots for per game | Shots on goal ÷ games | The strongest predictor by far (AUC 0.82 on its own). Shot stats are skill: r = 0.91–0.95 between a team's odd and even games |
| Schedule-adjusted goal differential | Goal differential per game + the average pre-game goal differential of the opponents faced | Adds on top of shots. Raw goal differential overlaps shots too much (r = 0.90); the adjusted one less |
| PDO | Shooting % (no empty-net goals) + save % | A **negative** weight once goal differential is in: a goal differential built on hot shooting or goaltending is trusted less |
| Home ice switch | 1 = home game, 0 = neutral site | An evenly matched home team wins about 52–53%. At a neutral site it's 50/50 by rule |

**Model settings** (same form as the men's): L2-regularized logistic regression, C = 1, no
separate intercept; stat features scaled but not centered, so 0 means "evenly matched".
Training data: 2025-26 games between teams that were D-I that season, complete box scores
only, ties dropped, both teams with at least 3 games.

## How well it predicts

**On the held-back end of 2025-26** (fold 4: the last 115 games, Feb 7 – Mar 22, including the
conference and NCAA tournaments):

| | Log loss | Brier | AUC | Accuracy |
|---|---|---|---|---|
| Always the home win rate | 0.683 | 0.245 | 0.500 | 60.0% |
| Win % only | 0.567 | 0.192 | 0.762 | 70.4% |
| **This model** | **0.541** | **0.184** | **0.781** | **73.9%** |

**On 2026-27, frozen and never seen before** (244 games through Nov 24):

| | Log loss | AUC | Accuracy |
|---|---|---|---|
| Always the home win rate | 0.695 | 0.500 | 51.2% |
| Win % only | **0.621** | 0.723 | 68.4% |
| **This model** | 0.627 | **0.753** | **70.1%** |

- **Women's games are far more predictable than men's:** about 0.75–0.78 AUC and 70–74% of
  winners picked, against about 0.64–0.67 and 64–67% for the men's. Women's D-I has wider
  gaps between teams (1 in 3 games has one side taking over 60% of the shots).
- **The first weeks are the weak spot.** With 6+ games of history on both teams the model is
  strong on 2026-27 (log loss about 0.55, 71–79% of winners). With 3–5 it's overconfident
  (log loss 0.837, worse than the home win rate), which is why it only ties win % overall so
  far. See "Known limits".

## What the EDA found, step by step

1. **Validation setup:** time-ordered 4-fold cross-validation (`TimeSeriesSplit`, k = 4),
   chosen by the pre-registered rule. k = 5 would leave test folds of 96 games, under the
   minimum of 100. Features were chosen on folds 1–3 and confirmed once on fold 4.
2. **Data checks:**
   - **D-I status is per season.** Franklin Pierce, Saint Anselm, Saint Michael's and Post were
     non-D-I in 2025-26 and moved up in 2026-27; their 2025-26 games aren't D-I games.
   - **Complete box scores only.** Two 2025-26 CHN pages are incomplete (one omits a team's 3
     goals, one has no scoring summary), so those games are excluded.
   - 698 D-I games, 696 used; 579 after the warm-up and dropping ties.
   - 5.9% of games are ties, including 29 shootouts (men's: 6.9%).
   - Home teams win 54.4% of decided games (men's: 55.4%).
3. **What wins a game, from inside it:**
   - Shots go with winning much more steeply than in the men's game: 17% win with under 40%
     of the shots, 83% with 60% or more (AUC 0.78; men's 0.64).
   - Special teams are close behind (0.77) and overlap shots more than the men's (r = 0.34).
   - Discipline barely matters (0.55). Score effects are real.
4. **Skill vs. luck** (tiers by cutoffs fixed in advance):
   - **Skill:** shot stats (r = 0.91–0.95), goal differential (0.81), 3rd-period goal
     differential (0.71), win % (0.69), special teams index (0.67).
   - **Partly skill:** PP%, PIM, **shooting % (0.48), PDO (0.42)**, times shorthanded, save %,
     % scoring first, PK%, PP chances.
   - **Luck:** one-goal game record (0.05).
   - **Unlike the men's,** shooting % and PDO repeat enough to stay candidates: finishing
     varies more between women's teams.
5. **Pre-game predictors:**
   - The season-to-date value beats recent form for every stat, in the same order as the
     men's (season > weighted > last 10 > 5 > 3).
   - Shots for per game is the best single predictor (gain 0.169, AUC 0.82; the men's best:
     0.071, 0.71). Raw and close-game shot share are near copies of it (r ≈ 0.95).
   - Goal differential beats win %; the special teams index beats PP% or PK%; team save %
     beats the likely starter's.
6. **Game context:** once team strength is known, nothing adds measurably. An evenly matched
   home team wins 53.3% (95% interval 48.5–58.2%). The game 1 winner of a series wins game 2
   70.8% of the time raw, but only +0.0004 on top of strength, and it fails the held-back
   fold: game 1's winner was mostly the better team.
7. **Combined model:** starting from shots for per game, only schedule-adjusted goal
   differential (+0.0017) and PDO (+0.0028) clear the minimum gain of 0.0013 (the men's 0.001
   scaled to the smaller sample) in 2 of 3 folds. C = 1 (C = 10 was better by less than its
   standard error).

## What didn't make it, and why

| Candidate | Reason |
|---|---|
| Raw and close-game shot share | Near copies of shots for per game (r = 0.95–0.96) |
| Raw goal differential, win % | Overlap shots for per game (r ≈ 0.9); the schedule-adjusted version carries the goal signal |
| Recent form (last 3/5/10, weighted) | Worse than the season figure alone, and adds nothing on top |
| Special teams (index, PP%, PK%, PP chances) | Predict alone (index AUC 0.74), but add nothing once shots and goal differential are known |
| Save %, shooting % alone | Their combination, PDO, is in |
| 3rd-period goal differential | Far weaker than full goal differential |
| % scoring first, streak | Weaker copies of team strength; streak failed the held-back fold |
| Strength of schedule alone | Barely predicts; failed the held-back fold. It's in the model inside the adjusted goal differential |
| Discipline (PIM, times shorthanded) | Doesn't predict results |
| Rest, back-to-backs, series game 1 result | Nothing beyond team strength |
| One-goal game record | Luck |

## Known limits and next steps

- **Early season (the main one).** With 3–5 games of history, a team's shots and goal
  differential are extreme, and the model turns them into overconfident probabilities: on
  2026-27 its 88% picks won 78%. **On the site, women's predictions are a rough guide until
  both teams have 6 games.**
- **Less data than the men's:** 579 training games against 957. Effects smaller than about
  0.003 in log loss can't be told apart from noise.
- **Neutral sites** are treated as exactly 50/50: only 30 neutral-site games in training.
- **Nothing about players:** injuries, a hot goalie or lineup changes are invisible to it.

## Plan: women's v2

The same plan as the men's v2 ([eda.md](eda.md#plan-model-v2-last-season-carried-over)):
start each team from a preseason rating carried over from last season, fading as the new
season's games come in. It targets exactly the early-season weakness above. Build it after
2026-27 ends, train on 2025-26 → 2026-27, test on 2027-28, and log it next to women's v1 for a
season. v1 stays frozen until then.
