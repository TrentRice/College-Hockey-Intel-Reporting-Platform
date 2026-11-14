# Features: team and player form

How a team and its players are playing over their **last N games**, next to the **season so
far**. Built for the scouting dashboard, and reusable by the model later.

## Where it lives

| Layer | What | File |
|---|---|---|
| Base tables | `features.team_games`, `features.skater_games`, `features.goalie_games`: one row per team, skater or goalie per played game | [db/features.sql](../db/features.sql) |
| Form logic | "Last N as of a date", with plain summary functions | [src/features/form.py](../src/features/form.py) |
| API | `GET /v1/teams/{id}/form`, `GET /v1/teams/{id}/player-form` | [src/api/routers/teams.py](../src/api/routers/teams.py) |

The base tables are **views** over the `hockey` tables, recreated by every load, so they're
never out of date. "Last N" is computed on request: a team has at most about 40 games, so any
N takes milliseconds and nothing has to be stored per N.

## Rules

- **`last=N`**: the team's N most recent games. N above the games played uses all of them
  (`games_used` says how many). Leaving it out means the whole season. N must be at least 1.
- **Season totals alongside**: whenever `games_used` is less than `games_played`, the
  response includes `season_totals` next to `window`, for comparison. For the whole season
  it's `null`.
- **`as_of=YYYY-MM-DD`**: only games **before** that date count. To scout a game, pass its
  date. A test checks this: removing every game from that date on doesn't change the
  numbers.
- **Players** are measured over the **team's** last N games. A player who missed some of
  them shows fewer games played.
- **No adjustments**: every number is the raw total or rate. Small windows are small samples;
  the season totals next to them give the context.

## What's included

**Team** (`/form`): record, win %, current streak, home, away and neutral records, goals
for and against (totals and per game), shots for and against per game, shot share, xG share
and xG per game, shooting %, team save %, PP % and PK %, PP chances and times shorthanded
per game, shorthanded goals, PIM per game, faceoff %. Also the list of games in the window:
opponent, score, OT or shootout, shots, and rest days before each game.

**Skaters** (`/player-form`): games, goals, assists, points, points per game, PP goals and
PP points, shots, shooting %, plus-minus, PIM.

**Goalies** (`/player-form`): games, starts, saves, shots against, goals against, save %,
GAA, time on ice. Also the **likely starter**: the goalie with the most starts in the team's
last 5 games, with ties going to the most recent start.

## Example

```
GET /v1/teams/8/form?last=5
```
```json
{
  "team": {"team_id": 8, "name": "Boston University"},
  "games_played": 11, "last": 5, "games_used": 5,
  "window":        {"record": "3-2-0", "shot_share": 0.474, "pp_pct": 0.4,   "...": "..."},
  "season_totals": {"record": "7-4-0", "shot_share": 0.532, "pp_pct": 0.229, "...": "..."},
  "games": ["... the 5 games, newest first ..."]
}
```

A dashboard uses `games_played` as the slider's maximum.
