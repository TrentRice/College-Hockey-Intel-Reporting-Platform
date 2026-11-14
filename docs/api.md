# CHIRP API

A read-only REST API over the hockey database ([db/schema.sql](../db/schema.sql)), built with
FastAPI. Code: [src/api/](../src/api/).

## Running it

**In Docker (normal use):**
```
make up        # builds the API image, starts Postgres + API, waits until healthy
make logs      # follow the logs
make down      # stop both (the data stays in the pgdata volume)
```
The API container restarts on its own whenever Docker Desktop is running. After changing API
code, run `make up` again to rebuild.

**Without Docker (while editing API code; reloads on save):**
```
make db-up     # database only
make serve     # http://127.0.0.1:8000
```
Stop the Docker API first (`docker compose stop api`), because both use port 8000.

Open **http://127.0.0.1:8000/docs** for interactive docs. Click **Authorize**, paste your
`API_KEY` from `.env`, and every endpoint can be tried in the browser.

From code or the terminal, send the key in the `X-API-Key` header:

```
curl -H "X-API-Key: $API_KEY" "http://127.0.0.1:8000/v1/teams?conference=Hockey%20East"
```

```python
import httpx2 as httpx  # or requests
r = httpx.get("http://127.0.0.1:8000/v1/teams/8/roster", headers={"X-API-Key": API_KEY})
```

## Endpoints

All `/v1` endpoints need the API key. A `season` parameter (e.g. `2026-27`) defaults to the
latest season.

| Endpoint | Returns |
|---|---|
| `GET /health` | API and database status, when the data was last refreshed, and the latest refresh's result (no key needed) |
| `GET /v1/seasons` | Seasons loaded, with scheduled and played game counts |
| `GET /v1/teams` | Teams in a season. Filters: `conference`, `search` (also matches old names), `d1_only` |
| `GET /v1/teams/{team_id}` | One team: name history and conference by season |
| `GET /v1/teams/{team_id}/games` | Schedule and results: opponent, home/away, score, W/L/T, OT, shootout, shots. Filter: `played` |
| `GET /v1/teams/{team_id}/season-stats` | Record, goals, shots, PP %, PK %, faceoff % |
| `GET /v1/teams/{team_id}/roster` | Skater and goalie season totals |
| `GET /v1/teams/{team_id}/form` | Team form over the last `last` games (capped at games played), with season totals alongside when that's fewer. Also takes `as_of`. See [features.md](features.md) |
| `GET /v1/teams/{team_id}/player-form` | Skater and goalie form over the team's last `last` games, season totals alongside, and the likely starting goalie |
| `GET /v1/games` | Games in date order. Filters: `season`, `date`, `date_from`/`date_to`, `team_id`, `played`, `conference_only`. Paged |
| `GET /v1/games/{game_id}` | Full box score: game info and officials, each team's stats by period, skaters, goalies, every goal (time, strength, scorer, assists) and penalty |
| `GET /v1/games/{game_id}/prediction` | Win probability from model v1: each team's inputs (games played, close-game shot share, goal differential) from games **before** the game's date, the home and away chances, and how much each factor moves them. Works for upcoming and played games. See below |
| `GET /v1/matchup` | Win probability for **any two D-I teams**, scheduled or not: `home_team_id`, `away_team_id`, `neutral`, `as_of` (games before this date; default today), `season`. Same model and response as a game's prediction, without the game |
| `GET /v1/rankings` | Every D-I team ranked by win model v1: chance to beat an average team on neutral ice, record, games played, and movement since a week earlier. `as_of` (games before this date), `min_games` (default 5), `limit`. Not adjusted for schedule |
| `GET /v1/predictions` | The prediction log, newest first: each game's logged chance, the favorite, whether it was backfilled or locked, and the result and whether the favorite won once played. Filters: `season`, `team_id`, `played`, `backfilled`, `reliable_only` (games past the 3-game warm-up). Paged |
| `GET /v1/predictions/summary` | How the log has done: graded games (ties excluded), accuracy, log loss and Brier score, a home-ice-only baseline, and calibration by the favorite's chance. Same filters |
| `GET /v1/players` | Player search. `search` matches any spelling and ignores accents ("jeremie" finds "Jérémie"). Filters: `season`, `team_id`, `position`. Paged |
| `GET /v1/players/{player_id}` | Profile: every spelling, plus each season's team and skater or goalie totals |
| `GET /v1/players/{player_id}/games` | Game log: opponent, result, and that game's stats. Filter: `season` |
| `GET /v1/leaders/skaters` | Ranked by `stat` (points, goals, assists, points_per_game, plus_minus, shots, pim). Filters: `position`, `conference`, `min_games`. Paged |
| `GET /v1/leaders/goalies` | Ranked by `stat` (save_pct, gaa, saves, starts). Qualified goalies only by default (a third of the team's minutes, the NCAA rule). Paged |

**Paging.** List endpoints return `{"items": [...], "total": N, "limit": 50, "offset": 0}`.
Use `limit` (at most 200) and `offset` to page through results.

**Ties.** Players with equal stats share a rank on leader boards (1, 1, 3).

**Merged player ids.** If new data showed two ids were the same player, the retired id
answers `308 Permanent Redirect` to the current one, query string included. Clients that
follow redirects get the right player automatically.

**Win probability.** `GET /v1/games/{game_id}/prediction` applies the frozen win model
(`models/win_model_v1.json`; how it was built: [eda.md](eda.md),
`notebooks/09_model.ipynb`).
- **The chance is for a game that has a winner.** Ties (about 7% of games) weren't in the
  training data.
- **`factors`** say how many points each input moves the home team's chance, compared with
  that input being even.
- **`reliable` is false** when a team has played fewer than 3 games, the training warm-up.
  The number is still given, with a `note`.
- **Games it can't predict** return `422`: a team still TBD, or a non-D-I opponent. For
  `/v1/matchup`: the same team twice, or a non-D-I team.
- **Without the model card** the endpoint returns `503`, and the rest of the API keeps
  working.
- **It stays in step with notebook 09.** The API computes the inputs in
  `src/models/win_model.py`, and notebook 09 checks that they match the training features
  exactly.

Errors: `401` for a missing or wrong key, `404` for an unknown team or season, and `422` for
a badly formed parameter (for example `season=2026`).

## Keeping it private

College Hockey News allows personal, non-commercial use of its data only (see
[schema.md](schema.md#data-source-and-use)), so the API must never be reachable by anyone
else. There are four layers:

1. **Localhost only.** Docker publishes the API on `127.0.0.1:8000` and the database on
   `127.0.0.1:5432`, and `make serve` binds to `127.0.0.1`. Nothing off this machine can
   connect. Tested: requests to this Mac's network address are refused on both ports. (Inside
   the container the API listens on `0.0.0.0`, but that only means "accept what Docker
   forwards". The `127.0.0.1:` on the published port decides who can reach it, and Docker
   bypasses the Mac firewall, so that prefix must never be removed.)
2. **API key.** With `API_KEY` set in `.env` (gitignored), every `/v1` request needs it. The
   app logs a warning at startup if no key is set.
3. **No secrets or data in the image.** `.dockerignore` is an allowlist: the image holds
   only `src/`, `config/`, `db/` and the dependency files. The key reaches the container as
   an environment variable at startup. The container runs as a non-root user, on a
   read-only filesystem, with all Linux capabilities dropped. Never push the image to a
   public registry.
4. **Read-only connections.** The API connects with `default_transaction_read_only=on`, so
   no endpoint can change data.

Never publish a port without `127.0.0.1:` or use `network_mode: host`, forward the port (router, ngrok, Cloudflare Tunnel, VS Code port
forwarding), or deploy it publicly without CHN's written permission. To reach it from your
own devices, use a private network such as Tailscale, together with the key.

## Tests

`make test` runs the API tests against a separate `hockey_test` database, loaded with
made-up rows from [tests/api/fixture.sql](../tests/api/fixture.sql). The real data is never
touched. CI runs the same tests against a Postgres service container. Without a reachable
Postgres, the API tests are skipped.
