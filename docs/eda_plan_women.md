# EDA plan: women's (2025-26)

The women's win model is built from scratch, the same way as the men's
([eda_plan.md](eda_plan.md)): the same steps, candidate features and overfitting guards,
**with every rule written down here before any women's feature result was looked at**
(2026-11-27). Nothing is carried over from the men's results: not the chosen k, not the
feature tiers, not the final features.

**Known before writing these rules** (from the Phase 1 data checks, not from modeling):
41 D-I teams in 2025-26, 698 D-I vs D-I games, 5.9% ties. About 600 games are expected after
the warm-up, against 957 for the men's, so several thresholds are scaled to the smaller
sample. Each scaled rule says how.

The work is in `notebooks/women/01`–`09`. Conclusions go in [eda_women.md](eda_women.md).

## Data and evaluation rules (same as the men's unless marked)

- **Training data:** 2025-26 only, D-I vs D-I games only.
  - **Women's:** D-I status is **per season** (`team_seasons.is_d1`). Four programs (Franklin
    Pierce, Saint Anselm, Saint Michael's, Post) were non-D-I in 2025-26 and moved up in
    2026-27; their 2025-26 games are not D-I games.
- **Final test set:** 2026-27 games played through the freeze, used once in step 9, never
  before.
- **One row per game,** home team minus opponent, built only from games on earlier dates.
- **Target:** home win = 1, loss = 0. Ties dropped.
- **Warm-up:** both teams have played at least 3 games.
- **Validation:** `TimeSeriesSplit` over games sorted by date.
- **No xG, no faceoffs, no skater ice time** (CHN doesn't publish xG or skater TOI for women;
  the men's EDA excluded xG and faceoffs too).

## Steps and their rules

1. **Choose k.**
   - **Scaled:** every test fold and the first training set need at least **100 games**
     (the men's 150 is about a sixth of their 957 rows; 100 is about a sixth of ~600).
   - Same procedure otherwise: the baseline and the four fixed check features
     (season-to-date goal differential, shot share, PP%, save %) at each eligible k from 3
     to 8; record only ranking stability; never pick k by score; no retries.
   - Tie-break (the men's amended rule): among k values whose rankings agree equally, the
     **largest** eligible k.
   - **Scaled default:** if the result is unclear, **k = 4**.
   - Lock k before step 5.

   **Result: k = 4, by the rule** (`notebooks/women/02_choose_k.ipynb`). 581 games after the
   warm-up (579 after step 2's fix; unchanged). Eligible k: 3 and 4 (k = 5 gives test folds of 96). Rankings identical at both;
   the tie-break takes 4. First training set 117 games, smallest test fold 116. Minimum gain
   for step 7: **0.0013**.
2. **Sanity checks:** the same checks as the men's (results mix, ties, games per team,
   missing values, both rows of each game agree).

   **Result: the data passes** (`notebooks/women/03_sanity_checks.ipynb`). Fix: only complete
   box scores are used (box score and goal list both match the official score), which removes
   two incomplete 2025-26 CHN pages (the second caught in step 3). Step 1 rerun, unchanged at
   k = 4, now 579 games. Ties 41 (5.9%); home teams win 54.4% of decided games; no missing
   values.
3. **What wins games** (in-game stats, for explanation only): the same tables as the men's.

   **Result** (`notebooks/women/04_what_wins_games.ipynb`): shot share is the strongest play
   stat (AUC 0.78; men's 0.64), special teams close behind (0.77) and overlapping with shots
   more than the men's (r = 0.34). Discipline is weak (0.55). Score effects are real (teams up
   2+ fall from 62% to 55% of 3rd-period shots).
4. **Skill vs. luck:** odd vs. even games, as for the men's. **The tiers are set by these
   cutoffs, fixed now:**
   - Tier 1 (skill): r ≥ 0.60. All windows tested in step 5.
   - Tier 3 (luck): r < 0.25. Dropped.
   - Tier 2: everything between. Season to date only.
   - The men's tiers are not reused.
   **Result** (`notebooks/women/05_skill_vs_luck.ipynb`; 41 teams, about 18 games per half):
   - **Tier 1:** shot share (r = 0.95), close-game shot share (0.93), shots for and against
     (0.91), goal diff (0.81), 3rd-period goal diff (0.71), win % (0.69), special teams index
     (0.67).
   - **Tier 2:** PP% (0.57), PIM (0.53), shooting % (0.48), PDO (0.42), times shorthanded
     (0.40), save % (0.38), % scoring first (0.36), PK% (0.31), PP chances (0.27).
   - **Tier 3, dropped:** one-goal game win % (0.05).
   - **Different from the men's:** the special teams index and 3rd-period goal diff are tier 1
     (all windows), and shooting % and PDO are tier 2 (the men's dropped them as luck). `01`
     now builds the features to match: 59 in all.
   - **Data handling, decided before step 5 ran:** a short window with no denominator (one
     game: a team with no power plays or penalty kills in its last 3) uses that team's
     season-to-date value.

5. **Pre-game predictors:** every feature × window allowed by step 4, scored per fold with a
   one-feature logistic regression against the baseline.
   - Select on folds 1 to k−1; confirm the shortlist once on fold k.
   - Keep a feature only if it beats the baseline in **a majority** of the selection folds
     (the men's: most of 4 folds; for k = 4 that's 2 of 3).
   - Within the fold-to-fold spread, take the simpler choice.
   - Overlap: of two features with |r| ≥ 0.8, keep the stronger.
   **Result** (`notebooks/women/06_pregame_predictors.ipynb`): far stronger signals than the
   men's (best single feature AUC 0.82 vs 0.71). Season to date beats recent form for every
   tier 1 stat. Shortlist: shots for per game, schedule-adjusted goal diff, 3rd-period goal
   diff, special teams index, % scoring first, streak, PP%, PDO, shooting %, PK%, save %, PIM,
   strength of schedule, PP chances. Fold 4 confirms 12 of 14 (streak, strength of schedule
   flagged).

6. **Home ice and rest:** each context feature tested on top of a strength-only model built
   from step 5's two strongest features, with step 5's keep rule.
   **Result** (`notebooks/women/07_home_ice_and_rest.ipynb`): no context feature added. Even
   home team wins 53.3% (48.5–58.2%). Game 1 of a series passes 2 of 3 by a hair (+0.0004) but
   fails fold 4 and the step 7 minimum.

7. **Model validation:** small regularized logistic models, adding one feature group at a
   time in the order step 5 ranks them.
   - **Scaled minimum gain:** a group is kept only if it improves log loss by at least
     **0.001 × √(957 / n)**, where n is the number of games after the warm-up (the men's
     0.001 scaled by the standard error's dependence on sample size). Computed in step 1.
   - …and only if it improves a majority of the selection folds.
   - C: as for the men's, 1 unless another value is better by more than its standard error.
   - **Model form, same as the men's:** no separate intercept; the home edge is multiplied
     by a home-ice switch (1 home, 0 neutral), so neutral-site games between equal teams
     are 50/50.
   **Result** (`notebooks/women/08_model_validation.ipynb`): shots for per game,
   schedule-adjusted goal differential and PDO (negative weight: a luck correction), plus the
   home ice switch; C = 1. Fold 4: log loss 0.541 (win % only 0.567, home rate 0.683), AUC
   0.781, accuracy 73.9%. Reviewed 2026-11-27: PDO kept.

8. **Write-up:** [eda_women.md](eda_women.md), with the final feature list.
9. **Freeze and test:** fit on all of 2025-26, freeze as `win_model_women_v1`
   (`models/win_model_women_v1.json`, card in `docs/model_women.md`), then score once on
   2026-27.

## Amendments

Any change to a rule after its step has run is recorded here with the reason, as the men's
were. None yet.

## Step 9 result (2026-11-27)

**Frozen: `win_model_women_v1`** (`notebooks/women/09_model.ipynb`), 579 games of 2025-26.
First test, 2026-27 through Nov 24 (244 games): log loss 0.627 (home rate 0.695, win % only
0.621), AUC 0.753, accuracy 70.1%. Strong once both teams have 6+ games (log loss about 0.55);
overconfident with 3–5 (0.837). The site should show women's predictions as a rough guide
until both teams have 6 games; the fix is women's v2 (last season carried over).

