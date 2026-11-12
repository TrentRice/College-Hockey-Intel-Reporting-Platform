# CHIRP

**College Hockey Intelligence & Reporting Platform**: a database of D-I men's college hockey games, box scores and players, built for scouting and modeling. Its first use is the BU Hockey Opponent Scouting Tool below.

## Project Status

[![CI](https://github.com/TrentRice/College-Hockey-Intel-Reporting-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/TrentRice/College-Hockey-Intel-Reporting-Platform/actions/workflows/ci.yml) [Data validation report](docs/data_validation.md)

**BU Hockey Opponent Scouting Tool** automates the repetitive statistical groundwork behind pre-game opponent scouting reports for Boston University Men's Hockey, using only public data. The end goal is a short pre-game report for BU's next opponent covering schedule and results, recent form, special teams, top scorers, goalie usage, and eventually model-based predictions.

### Completed

**League-wide schedule/results scraper (College Hockey News)**
Scouting an opponent requires that opponent's full season. `chn_team_schedule_scraper.py` collects schedules and results for all 63 Division I teams:

- Raw HTML is cached in `data/raw/chn/schedules/` (not committed), so re-runs don't re-download
- Outputs `data/processed/chn/all_games_<season>.csv`, one row per game with home and away team; filter on `home_team`/`away_team` for one team's season
- Fields include date, result, score, home/away/neutral, opponent, overtime, exhibition, conference flags, event notes (Beanpot, tournaments), and box score / metrics URLs
- Includes team and opponent conference, so same-league games can be identified

**Box score ingestion (College Hockey News)**
Two steps, run after the schedule scraper:

- `chn_boxscore_downloader.py` saves each played game's box score page to `data/raw/chn/boxscores/<season>/` (incremental, so in-season re-runs only fetch new games)
- `chn_boxscore_parser.py` turns those pages into `data/processed/chn/box_*_<season>.csv`:
  - `box_games`: venue, attendance, officials, OT periods, shootout result (score and game flags are in `all_games`)
  - `box_team_stats`: goals/shots by period, PP/PK, PIM, faceoffs, xG, empty-net time (one row per team per game)
  - `box_skaters`: G, A, +/-, shots, TOI, PIM, faceoffs, F/D position
  - `box_goalies`: saves, GA, TOI, starter flag
  - `box_goals`: period, time, strength (EV/PP/SH/EN/EA/4x4), scorer, assists
  - `box_penalties`: period, time, player, minutes, infraction
- The parser checks that goals, GA, and penalty counts agree across sections and with the schedule; mismatches go to `box_parse_issues_<season>.csv`

```
uv run python -m src.ingestion.chn_team_schedule_scraper
uv run python -m src.ingestion.chn_boxscore_downloader
uv run python -m src.ingestion.chn_boxscore_parser
```

**Data validation**
Every season on disk (2025-26 and 2026-27) is checked by `src/evaluation/validate_chn_data.py`, which writes [docs/data_validation.md](docs/data_validation.md). It cross-checks each box score against the separate schedule pages (final score, overtime) and checks that the sections of each box score agree (period totals, scoring summary, skater goals, penalties, goalies, faceoffs). Every remaining mismatch is an error on the source page, listed in the report with a link to it. The data is gitignored, so run the checks locally with `make validate`.

**Database schema and stable IDs**
[db/schema.sql](db/schema.sql) is a PostgreSQL star schema: dimension tables (teams, players, seasons, conferences) and fact tables (games, team/skater/goalie game stats, goals, penalties), plus season-total views. Box scores name players with plain text, so `src/transform/id_mapping.py` assigns every team and player a stable id. It links seasons by CHN player id, then by team and name, and catches transfers who haven't scored yet. The ids are written to `data/processed/ids/`, and each run reuses the ids from the last one. Details, including what CHN's terms allow, are in [docs/schema.md](docs/schema.md). Rebuild with `make ids`.

**PostgreSQL database**
`make db-up` starts Postgres 17 in Docker, and `make load` loads both seasons into it: about 85k rows in about a second, as a full refresh in one transaction. The loader refuses any name it can't map to an id, and checks row counts and season totals before committing. Query the data with `make psql`, or connect any SQL client to `localhost:5432` (user, password and database are all `hockey`). See [docs/schema.md](docs/schema.md#loading-the-database).

**API (FastAPI)**
`make up` runs Postgres and a read-only REST API in Docker at http://127.0.0.1:8000, with interactive docs at `/docs`. It covers teams (schedule and results, season stats, roster), games (search by date or team, plus full box scores with every goal and penalty), players (accent- and spelling-insensitive search, profiles, game logs), and skater and goalie leader boards. It is private by design: every port is published to localhost only, the image holds no data or secrets, it needs an API key (`X-API-Key`, set in `.env`), and uses read-only database connections. Tests run against a separate database of made-up rows, in CI as well. See [docs/api.md](docs/api.md).

**Automated refresh**
During the season the data refreshes itself. A `pipeline` service in Docker runs scrape → download → parse → validate → ids → load once a day after 5 a.m. Eastern, and catches up if the Mac was asleep. Validation acts as a gate: if it fails, the load is skipped and the API keeps the last good data. Every run is recorded (`make runs`) and shown on the API's `/health`. Requests check CHN's robots.txt first. Run it by hand with `make refresh`. See [docs/pipeline.md](docs/pipeline.md).

### Planned

- **Feature building** (`src/features/`): record, last-5 form, goals for/against, shot differential, special teams, goalie workload, top scorers, point pace
- **Report generation** (`src/reports/`): HTML or PDF opponent report for BU's next game
- **Modeling** (`src/models/`): game outcome predictions for each BU game

### Data

The data comes from College Hockey News and isn't in this repo: CHN's terms allow personal, non-commercial use only (see [docs/schema.md](docs/schema.md#data-source-and-use)). Rebuild it locally with the scrapers above, then `make validate`, `make ids`, `make db-up` and `make load`.

### Tech Stack
Python, requests, BeautifulSoup (lxml), pandas, PostgreSQL 17, FastAPI, Docker Compose, psycopg, managed with uv.

### Project Structure
```
data/{raw,interim,processed}/
db/schema.sql
src/{ingestion,transform,db,api,evaluation,features,models}/
```
