# Scouting dashboard

An interactive Streamlit app for scouting an opponent over their **last N games**, next to
their **season so far**. Code: [src/dashboard/](../src/dashboard/).

## Opening it

```
make up          # starts everything in Docker, including the dashboard
```
Then go to **http://127.0.0.1:8501**.

While working on the dashboard code, `make dashboard` runs it outside Docker and reloads on
save. Stop the Docker one first (`docker compose stop dashboard`), because both use port 8501.

## Using it

**Sidebar**
- **Your team**: defaults to Boston University. Its next game decides the default opponent.
- **Scout**: *Next opponent* picks your team's next opponent automatically. *Any team* lets
  you choose one.
- **Only games before**: defaults to the scouted game's date, so nothing from that game or
  later is counted. Pick an earlier date to see how a team looked at that point.
- **Last N games**: from 1 to the number of games the team has played before that date.
  It defaults to 5.

**Team tab**
- Six headline numbers for the last N games, each with its change from the season so far.
  Green or red shows whether the change is good or bad; "no change" is neutral.
- A full table: last N, season, and the difference for 20 stats. The difference is
  **green when the last N games are better** than the season and **red when worse**. Higher is
  better except for goals against, shots against, times shorthanded and PIM per game, where
  lower is better. It also keeps its + or − sign, so color isn't the only signal.
- **Actual vs expected goal differential by game**, in one chart on one axis (goals). Bars
  are the actual goal differential (blue = won by, red = lost by). Diamonds joined by a line are
  the *expected* goal differential from CHN's xG (xG for minus xG against). If the end of
  the bar is **above** its diamond, the team did better than its chances suggested (finishing or
  goaltending); **below** means worse. That holds for losses too: losing by 1 when expected to
  lose by 2 puts the bar's end above the diamond, which is an overperformance. The selected games are shaded. Hover over
  any bar or diamond for the date, opponent, result, both differentials, xG for and against,
  shot share, xG share and shots.
- The games in the window, with rest days before each.

**Players tab**
- The **likely starting goalie**: most starts in the last 5 games.
- Skaters over the last N games (GP, G, A, P, P/GP, PP points, shots, Sh%, +/-, PIM), with
  season GP, G, P and P/GP alongside. **P/GP diff** (last N minus season) sits next to P/GP:
  green when a player is scoring more, red when less. A toggle shows skaters who didn't play
  in those games.
- Goalies over the last N games, with season numbers alongside. **SV% diff** (last N minus
  season) sits next to SV%: green when a goalie is saving a higher share, red when lower.

**vs your team tab**
- Both teams over the same last N games (each capped at its own games played), with a
  **Better** column on every stat: **green when it's your team, red when it's the opponent,
  yellow "Tie"** when they're level as displayed. Lower is better for goals against, shots
  against, times shorthanded and PIM. Records (overall, home, away) compare win % (ties count
  half). For the streak, any win streak beats a tie, which beats any losing streak; between two
  win streaks the longer is better, and between two losing streaks the shorter is. "n/a"
  means one side has nothing to compare, such as no away games yet or no xG.
- Meetings between the two teams earlier this season.

**Win probability tab**: your team against the scouted team, like the other tabs.
- **Next opponent:** the scheduled game, using each team's games before that date.
- **Any team:**
  - Your team against whichever team you pick, scheduled or not, using games before the
    sidebar's "Only games before" date.
  - Pick where it's played: **Home / Away / Neutral site**. It starts at the venue of their
    next scheduled meeting if there is one, and at Home otherwise.
  - Switching venue shows what home ice is worth in that matchup.
- **What it shows:**
  - Both teams' chances, as numbers and a bar.
  - The **biggest factor**, plus a table of the three inputs side by side: close-game shot
    share, goal differential per game, and home ice.
  - **Effect on chance** is how many points each factor moves your team's chance compared
    with it being even: green helps, red hurts.
- **A warning** appears when a team has played fewer than 3 games, below the model's
  warm-up.
- **No prediction** for a game against a non-D-I team or a TBD opponent. The tab says why.

**Sorting.** Click a column header to sort, and click again to reverse. The difference
columns hold real numbers, so ascending puts the biggest drop first and descending the biggest
gain first. In the team table the rows mix units (percentage points and per-game numbers), so
sorting there groups by size rather than comparing like with like.

## How it fits together

The dashboard reads **only from the API** (`/v1/teams/{id}/form`, `/player-form`,
`/games`, `/v1/games/{id}/prediction`, `/v1/matchup`, `/health`) with your `API_KEY`. It never connects to
the database. Responses are
cached for 5 minutes, and the sidebar shows when the data was last refreshed. If the latest
nightly refresh failed or was blocked, it shows a warning.

## Privacy

- **Localhost only.** Docker publishes it on `127.0.0.1:8501`, and `.streamlit/config.toml`
  sets `127.0.0.1` for local runs. Tested: connections from this Mac's network address are
  refused.
- **No usage statistics.** Streamlit normally sends anonymous usage data. It's turned off
  in `.streamlit/config.toml` and again in the container's environment.
- The container is set up like the others: a non-root user, a read-only filesystem, and all
  Linux capabilities dropped.

## Tests

[tests/dashboard/](../tests/dashboard/) runs the whole app with Streamlit's test harness. The
app's API calls go to the real API over the made-up test database, so a test covers the
dashboard, the API and the database together. The `logic.py` helpers (formatting,
differences, next game, the head-to-head "Better" column) have their own unit tests.
