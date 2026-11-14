# EDA plan (2025-26)

**Goal:** find which pre-game features predict winning, and in what form, so the model's
features are chosen on evidence. **No xG** (another model's output) and **no faceoffs**.

## Data and evaluation rules

- **Training data:** 2025-26 only, **D-I vs D-I games only** (1,147 games). CHN records
  non-D-I opponents only partly. **2026-27 is the final test set:** used
  once at the end, never during the EDA.
- **One row per game**, from the home team's view (at neutral sites, the team CHN lists
  as home). Every feature is **home team minus opponent**, built only from games played
  **before that date**.
- **Target:** home win = 1, loss = 0. Ties are dropped (79 games).
- **Warm-up:** a game counts once both teams have played at least 3 games.
- **Validation:** `TimeSeriesSplit` over games sorted by date. Every fold trains only on
  earlier games.
- **Built as Jupyter notebooks** in `notebooks/`, numbered in order.
  `01_pregame_features.ipynb` builds the features and runs the leakage checks. Later
  notebooks load it with `%run ./01_pregame_features.ipynb`.
- **No CHN data in git:** nbstripout removes notebook outputs when you commit, while your
  local copies keep them. It's set up through `.gitattributes`. After a fresh clone, run
  `uv run nbstripout --install` once. `docs/eda.md` holds conclusions, not data tables.

## Steps

1. **Choose k.** Find the k values where every test fold and the first training set have
   at least ~150 games. Run the baseline and four fixed check features (season-to-date goal
   differential, shot share, PP%, save %) at k = 3–8. Pick the smallest k where the
   feature ranking stops changing. Rules:
   - Record only stability numbers, not which feature wins.
   - Never pick k by best score.
   - Make no retries with other check features.
   - If the result is unclear, use k = 5.
   - Lock k before step 5.

   **Result: k = 5 locked** (see `02_choose_k.ipynb`).
   - 957 games after the warm-up and dropping ties.
   - The ranking was identical at every eligible k (3, 4, 5). The rule's tie-break picked
     3, but k = 3 leaves only 2 folds for step 5's feature selection.
   - k = 5 still meets the size rule: first training set 162 games, smallest test fold 159.
   - Amended tie-break: among k values whose rankings agree equally, take the largest
     eligible one.
2. **Sanity checks:**
   - mix of wins, losses, OT and shootouts, and how many games are dropped as ties
   - games per team, and missing values

   **Result: the data passes** (see `03_sanity_checks.ipynb`).
   - **One fix:** the single game against a non-D-I team (0 shots recorded for that team) is
     now excluded from the features. Step 1 was rerun and is unchanged: k = 5.
   - **Ties:** 79 games (6.9%) are ties, 56 of them settled by shootout.
   - **Consistency:** both team rows of every game agree, with no impossible counts.
   - **Coverage:** every team played 30–43 games. There are no missing values, raw or in the
     features.
   - **Baseline:** home teams win 55.4% of decided games. 44% of team-games come the day after
     that team's previous game (back-to-backs).
3. **What wins games (in-game stats, for explanation only):** win % by shot share,
   special teams differential, PIM, times shorthanded, scoring first, and the lead after the
   1st and 2nd periods. Watch for score effects.

   **Result** (see `04_what_wins_games.ipynb`):
   - **Shots:** win % rises steadily with shot share, from 35% to 68% (AUC 0.64).
   - **Score effects are real:** teams up 2+ after two periods fall from 55% to 49% of the
     shots in the 3rd, so full-game shot share understates teams that often lead.
     Close-game shot share is added to step 5.
   - **Special teams** are the strongest play stat (AUC 0.76), but they're partly the score
     itself. Step 4 decides whether PP% and PK% repeat.
   - **Discipline is weak** (AUC 0.55). Times shorthanded and PIM overlap (r = 0.66), so test
     times shorthanded and keep PIM only if it adds something.
   - **Game state** (first goal 75%, leading after two 92%) can't be used before a game.
   - **Shots and special teams are separate signals** (r = 0.19).
   - **Step 5 priority:** shots and special teams first. Team strength is the reference to
     beat. Discipline and game state come last.
4. **Skill vs. luck:** correlate each stat between each team's odd and even games.

   **Result** (see `05_skill_vs_luck.ipynb`; 63 teams, about 18 games per half):
   - **Tier 1, skill:** shot share, shots for and against, close-game shot share and goal
     differential (r = 0.70–0.82). They reach half signal in 4–8 games. Test all windows.
   - **Tier 2, partly skill:** special teams (PP%, PK%, their index, PP chances, times
     shorthanded), save %, PIM, % scoring first and 3rd-period goal differential
     (r = 0.30–0.47). They need 20–40 games. **Season-to-date only.**
   - **Tier 3, luck, dropped:** shooting % (r = 0.25), one-goal game win % (r = 0.08) and
     PDO.
   - **Special teams** decide games (step 3) but are hard to predict: PK% barely carries from
     the first half to the second (r = 0.16). Test the combined index first.
5. **Pre-game predictors:** score every feature × window (last 3, 5, 10, season, weighted
   average) per fold with a one-feature logistic regression. Measure log loss and AUC
   against the baseline.
   - **Overfitting guards:**
     - make selections on folds 1 to k−1 only, then confirm the shortlist once on the
       last fold
     - keep a feature only if it beats the baseline in most folds, not just on average
     - when two choices are within the fold-to-fold spread, take the simpler one

   **Result** (see `06_pregame_predictors.ipynb`; 49 features, rules fixed in advance):
   - **The season to date beats recent form for every tier 1 stat**, in the order season >
     ewm > last 10 > last 5 > last 3. Step 7 tests whether ewm adds anything on top of the
     season figure.
   - **Shortlist:**
     - Core: close-game shot share, goal diff (no empty-net goals), shots for per game. Gain
       0.048–0.071, 4/4 folds.
     - Secondary: % scoring first, special teams index, streak, PP%.
     - Marginal: save %, PP chances per game, sos.
   - **Dropped:**
     - By the keep rule: times shorthanded, PIM, likely starter's save % (worse than team
       save %) and form vs. season.
     - For overlap (|r| ≥ 0.8): raw shot share, raw goal diff, adjusted goal diff, shots
       against, win %, 3rd-period goal diff and PK%.
   - **Fold 5 confirms 9 of 10.** PP chances per game is flagged. Gains are smaller there
     (tournament games).
   - **Best single feature:** AUC 0.71 (0.64 on fold 5). Expect modest accuracy. The goal
     is calibrated probabilities.
6. **Home ice and rest:**
   - size of the home ice advantage
   - rest days and back-to-backs
   - the second game of a series, and who won the night before

   **Result** (see `07_home_ice_and_rest.ipynb`; each feature tested on top of a strength
   model, same fold rules as step 5):
   - **No context feature is kept.** All six lost to the strength-only model, beating it in at
     most 2 of 4 folds.
   - **Home ice:** an evenly matched home team wins 53.4% (49–57%). The model's intercept
     carries this. The neutral-site effect can't be learned from 54 games, so in step 7
     consider setting the home edge to zero at neutral sites by rule.
   - **Rest:** 79% of games have equal rest. No signal.
   - **Back-to-backs:** both teams are on one in 423 of 432 cases, so they can't be measured.
   - **Game 1 of a series:** a raw 61.5% vs. 44.5% split, but 0.0 points on top of strength.
     The game 1 winner was just the better team.
7. **Validation and write-up:**
   - small regularized logistic models, adding one feature group at a time
   - `docs/eda.md` with conclusions and the final feature list

   **Result** (see `08_model_validation.ipynb` and [eda.md](eda.md)):
   - **Final set:** close-game shot share and goal diff (no empty-net goals), both season to
     date, plus the home ice switch. C = 1.
   - **Amendment:** each group needs a gain of at least 0.001. That drops % scoring first,
     which the first run kept on +0.0001, and changes nothing else.
   - **Fold 5:** log loss 0.627 (the first run's three-feature model: 0.626), against 0.639
     for win % only and 0.675 for the home win rate. AUC 0.639. Calibration is good.
   - **2026-27 is untouched**, kept for the final test.

## Features to test

| Group | Features |
|---|---|
| Team strength | win % (ties count half); goal diff/game with and without empty-net goals; strength of schedule; opponent-adjusted goal diff |
| Shots | shot share; **close-game shot share** (only periods that started tied or within one goal; added after step 3); shots for/game; shots against/game |
| Finishing and goaltending | save %; likely starter's save % (shooting % and PDO dropped after step 4: luck) |
| Special teams and discipline | PP%; PK%; special teams index; PP chances/game; times shorthanded/game; PIM/game |
| Game state | % scoring first; 3rd-period goal diff (one-goal record dropped after step 4: luck) |
| Momentum | streak; last-N win % vs. season |
| Context | home/away/neutral; rest-day difference (capped at 7); back-to-back; second game of a series, plus who won the night before; games played (for checking reliability only) |

**Windows:**
- **Tier 1 stats** (shots, close-game shots, goal differential, win %): last 3, last 5, last 10,
  season to date, and an exponentially weighted average.
- **Tier 2 stats** (special teams, save %, discipline, game state): season to date only.

See step 4 for the tiers.
