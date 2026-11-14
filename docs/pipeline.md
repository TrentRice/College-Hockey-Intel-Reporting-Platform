# Data refresh pipeline

Keeps the database current during the season with no manual steps. Code:
[src/pipeline/](../src/pipeline/).

```
schedules ─► box scores ─► parse ─► validate ─► ids ─► load ─► predict
 (scrape)    (new only)            (gate)              (one transaction) (log the week)
```

| Step | Runs | Notes |
|---|---|---|
| schedules | `chn_team_schedule_scraper --strict` | Re-fetches a team's page only if the saved copy is over 6 hours old. If any team fails, the existing `all_games` is kept and the run stops. |
| boxscores | `chn_boxscore_downloader` | Only games not already downloaded. A single missing page doesn't stop the run; validation catches it. |
| parse | `chn_boxscore_parser` | Current season |
| validate | `validate_chn_data --strict` | **Gate.** An unexplained mismatch stops the run before the load. |
| ids | `id_mapping` | Reuses existing ids |
| load | `src.db.load` | Full refresh in one transaction |
| predict | `src.pipeline.predict` | Logs win model v1's chance for every D-I game in the next 7 days, in `predictions.game_predictions`. Each night updates a game's prediction until game day; the game-day run locks it. Played games not yet logged are backfilled and marked so. Also `make predict` |

## Running it

**Automatically.** `make up` starts the `pipeline` service along with the database and API.
It checks every 15 minutes and runs the refresh once a day:

- after **5:00 a.m. Eastern**, when late West Coast games are final
- **catching up** if the Mac was asleep or Docker was closed at 5 a.m.
- **retrying** a failed or blocked run after an hour, at most 3 tries a day
- in the **off-season** (May to August), on Mondays only

**By hand.** `make refresh` runs it now, for example to pull in tonight's games before a
scouting report. A manual run counts as the day's run.

**Checking on it:**
```
make runs                       # the last 10 runs: when, how long, status, new games
docker compose logs pipeline    # the scheduler's own log
ls logs/refresh/                # one log per run, plus that run's validation report
```
`GET /health` on the API shows `data_as_of` (the last successful refresh) and the most recent
run's status.

## What each status means

| Status | Meaning | What to do |
|---|---|---|
| `success` | Everything loaded | Nothing |
| `blocked` | Validation found an unexplained mismatch, so the load was skipped. The API keeps serving the last good data. | Read `logs/refresh/<run>.validation.md`. A late box score usually clears up on the hourly retry. A real error on CHN's page goes in `REVIEWED_SOURCE_ERRORS` in `validate_chn_data.py`. |
| `failed` | A step broke: a network problem, CHN down, or a bug | Read `logs/refresh/<run>.log`. It retries in an hour. |

## Safety

- **One run at a time.** A Postgres advisory lock is held for the whole run, so a manual
  `make refresh` can't overlap the scheduled one.
- **The database is never half-updated.** The load is a single transaction, and it only
  runs after validation passes.
- **Polite to CHN.** It runs once a day (weekly in the off-season), keeps the scrapers'
  delays between requests (1.5 to 2 s), and checks robots.txt before every request
  ([src/ingestion/http.py](../src/ingestion/http.py)), skipping anything CHN asks crawlers
  to avoid.
- **Run history** lives in `ops.pipeline_runs`, outside the `hockey` schema that every load
  rebuilds. Logs are kept for the last 60 runs and are gitignored.
- **No ports.** The pipeline container only makes outgoing requests, to CHN and to the
  database. It runs as a non-root user on a read-only filesystem. Only `data/` and `logs/`
  are writable, and both are folders on this Mac.

## Cost

A nightly run takes a few minutes, mostly the deliberate pauses between requests. Between
runs the scheduler sleeps.
