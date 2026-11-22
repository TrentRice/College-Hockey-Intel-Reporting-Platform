# Data refresh pipeline

Keeps the data current during the season with no manual steps. It runs every morning in
GitHub Actions, in the private `CHIRP-data` repo ([cloud.md](cloud.md)). Code:
[src/pipeline/](../src/pipeline/), plus [src/cloud/nightly.py](../src/cloud/nightly.py) for
the GitHub job.

```
schedules ─► box scores ─► parse ─► validate ─► ids ─► load ─► predict ─► backup
 (scrape)    (new only)            (gate)              (one transaction) (log the week) (prediction log)
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
| backup | `src.pipeline.backup` | Copies the prediction log to `data/backups/predictions_<date>.csv.gz` and keeps the newest 30. Also `make backup` |

## Running it

**Automatically, in GitHub Actions.** The `CHIRP-data` repo's workflow
([deploy/data-repo/.github/workflows/refresh.yml](../deploy/data-repo/.github/workflows/refresh.yml))
starts at 5:30, 8:30 and 11:30 a.m. EST (an hour later in summer). Each start runs
`python -m src.cloud.nightly`, which applies the rules in
[src/pipeline/scheduler.py](../src/pipeline/scheduler.py):

- after **5:00 a.m. Eastern**, when late West Coast games are final
- **retrying** a failed or blocked run on the next start, at most 3 tries a day
- in the **off-season** (May to August), on Mondays only

Each job starts with an empty Postgres. So it first restores the run history
(`pipeline_runs.csv`) and the newest prediction-log backup, then runs the steps above, then
commits to `CHIRP-data`: everything after a success, only the history and logs otherwise. The
public app picks up a new commit within about 10 minutes.

Git doesn't keep file times, so the workflow marks the saved schedule pages as old before
scraping; otherwise the 6-hour reuse rule would skip every page.

**By hand.** In `CHIRP-data` on GitHub: **Actions → Nightly refresh → Run workflow** (tick
*force* if today's run already succeeded). On the Mac, `make refresh` scrapes into the local
database instead. That's rarely needed: `make data-pull` gets the nightly job's result.

**Checking on it:**
- **The Actions tab** in `CHIRP-data`: each run, green or red. GitHub emails you when one fails.
- **`pipeline_runs.csv`** in `CHIRP-data`: every run, with when, how long, status and new games.
- **`logs/refresh/`** in `CHIRP-data`: one log per run, plus that run's validation report.
- The dashboard's sidebar and the API's `GET /health` show when the data was last refreshed
  and whether the latest run failed.

## What each status means

| Status | Meaning | What to do |
|---|---|---|
| `success` | Everything loaded | Nothing |
| `blocked` | Validation found an unexplained mismatch, so nothing was committed. The site keeps serving the last good data. | Read `logs/refresh/<run>.validation.md` in `CHIRP-data`. A late box score usually clears up on the next retry. A real error on CHN's page goes in `REVIEWED_SOURCE_ERRORS` in `validate_chn_data.py`. |
| `failed` | A step broke: a network problem, CHN down, or a bug | Read `logs/refresh/<run>.log` in `CHIRP-data`, or the run in the Actions tab. It retries on the next start. |

## Safety
- **The prediction log is backed up nightly** into `CHIRP-data`, where git keeps every
  version. It's the one thing that can't be rebuilt from CHN. Locally, `make db-reset` backs
  it up first and stops if that fails (`FORCE=1` skips the backup); afterwards
  `make data-pull` reloads everything.

- **One run at a time.** A Postgres advisory lock is held for the whole run, so a manual
  `make refresh` can't overlap another, and the workflow runs one job at a time.
- **The database is never half-updated.** The load is a single transaction, and it only
  runs after validation passes.
- **Polite to CHN.** It runs once a day (weekly in the off-season), keeps the scrapers'
  delays between requests (1.5 to 2 s), and checks robots.txt before every request
  ([src/ingestion/http.py](../src/ingestion/http.py)), skipping anything CHN asks crawlers
  to avoid.
- **Run history** lives in `ops.pipeline_runs`, outside the `hockey` schema that every load
  rebuilds, and in `CHIRP-data/pipeline_runs.csv` between jobs. Logs are kept for the last
  60 runs, in `CHIRP-data` and never in this repo.
- **Private logs.** The workflow lives in the private data repo, so its logs, which quote
  data, aren't public.

## Cost

Free. A nightly run takes about 2–6 minutes, mostly the deliberate pauses between requests:
well within GitHub's 2,000 free Actions minutes a month for private repos.

## The Docker scheduler (optional)

The local Docker stack still has a `pipeline` service, which runs the same refresh once a
day on the Mac ([src/pipeline/scheduler.py](../src/pipeline/scheduler.py)). It's off by
default, a Compose profile, so the Mac and GitHub don't both scrape CHN. To run it on purpose:
`docker compose --profile pipeline up -d pipeline`.
