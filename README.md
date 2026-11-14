# CHIRP

**College Hockey Intelligence & Reporting Platform.** A private, self-updating platform for
D-I men's college hockey. It has a database of every game, box score and player, an API, a
scouting dashboard, and a win-probability model that's tested against real results. It was
built for scouting Boston University's opponents.

[![CI](https://github.com/TrentRice/College-Hockey-Intel-Reporting-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/TrentRice/College-Hockey-Intel-Reporting-Platform/actions/workflows/ci.yml)

## What it does

The dashboard at http://127.0.0.1:8501 has six tabs:

| Tab | What it shows |
|---|---|
| **Team** | The scouted team over its last N games next to its season: 20 stats, colored better or worse, and actual vs. expected goal differential by game |
| **Players** | Skaters and goalies over the same games, with season numbers alongside, and the likely starting goalie |
| **vs your team** | Both teams side by side on every stat, and this season's meetings |
| **Win probability** | Your team's chance against the next opponent, or any team at a venue you pick, with what drives it |
| **Rankings** | A model "poll": the top 20 by chance to beat an average team on neutral ice, with movement since last week |
| **Model record** | Every prediction, logged before the game and checked against the result: accuracy, log loss, calibration |

It defaults to BU and its next opponent. The sidebar picks your team, the team to scout, a
cut-off date ("only games before"), and how many recent games to look at.

## Quick start

```bash
cp .env.example .env     # set API_KEY
make setup               # dependencies, plus notebook output stripping
make up                  # Postgres, API, nightly pipeline, dashboard (Docker)
make refresh             # first load: scrape College Hockey News and fill the database
```

Then open http://127.0.0.1:8501 (dashboard) or http://127.0.0.1:8000/docs (API). After the
first load, the data refreshes itself every morning. Day-to-day commands are in
[CONTRIBUTING.md](CONTRIBUTING.md).

## How it works

```
College Hockey News ─► scrape ─► parse ─► validate ─► ids ─► load ─► predict ─► backup   (nightly)
                                                              │
                                     Postgres ◄────────────────┘
                                        │ read-only
                                     CHIRP API (key required) ─► Dashboard
```

- **Data:**
  - Scrapers collect every D-I team's schedule and every box score: goals, shots by period,
    special teams, skaters, goalies, goals and penalties.
  - A validation gate cross-checks them. If the numbers don't add up, the load is skipped
    and the last good data keeps serving.
  - Stable ids follow players across seasons, spelling changes and transfers.
- **Database:** PostgreSQL 17, loaded as a full refresh in one transaction.
- **API:** FastAPI with read-only connections and an API key. It covers teams, games, box
  scores, players, leaders, form, win probabilities, rankings and the prediction log.
- **Nightly pipeline:**
  - Runs after 5 a.m. Eastern and catches up if the Mac was asleep. Every run is recorded.
  - Logs each game's win probability before the game and locks it on game day.
  - Backs up the prediction log.
- **Docker:** three small images from one Dockerfile (api, pipeline, dashboard), each with
  only its own dependencies.

Details: [architecture](docs/architecture.md) · [database](docs/schema.md) ·
[pipeline](docs/pipeline.md) · [API](docs/api.md) · [dashboard](docs/dashboard.md) ·
[form features](docs/features.md) · [data validation](docs/data_validation.md)

## The win model

**Home win probability = logistic(close-game shot share + goal differential + home ice),**
each team's season so far, home minus away.
- **Neutral sites get no home edge.**
- **Ties are left out:** it's the chance of winning a decided game.

**How it was chosen:** an EDA in eight notebooks (`notebooks/01`–`08`, written up in
[docs/eda.md](docs/eda.md)), with rules fixed before each step and features chosen on
time-ordered folds of 2025-26.
- **What predicts:** shot share does most of the work, and goal differential adds a little.
- **What doesn't help:** recent form, special teams, save %, rest and back-to-backs added
  nothing on top.

**How it was tested:** it was frozen (`notebooks/09`), then tested on 2026-27 games it had
never seen. Through Nov 13 that's 173 games: **log loss 0.643 vs 0.680 for the home win
rate, AUC 0.67, 64% of winners picked.** The live record is on the Model record tab.

**Limits:** it's weak in a season's first weeks, it isn't adjusted for strength of schedule,
and it knows nothing about players. Full card: [docs/model.md](docs/model.md).

**Next:** v2 carries last season over, so early-season predictions and rankings work from
opening night. It's planned for 2027-28, once 2026-27 is complete (plan in
[docs/eda.md](docs/eda.md)).

## Data and privacy

The data comes from [College Hockey News](https://www.collegehockeynews.com), whose terms
allow **personal, non-commercial use only**. So:
- **None of it is in this repo:** scraped pages, CSVs, backups, logs and notebook outputs are
  all gitignored or stripped.
- **Everything runs on one machine:** every port is bound to 127.0.0.1, the API needs a key,
  and the scrapers respect robots.txt.
- **Only 2025-26 onward is kept** (see [docs/schema.md](docs/schema.md#data-source-and-use)).

## Tech stack

Python 3.12, uv · requests, BeautifulSoup/lxml, pandas · PostgreSQL 17, psycopg ·
FastAPI · Streamlit + Altair · scikit-learn and Jupyter (model building) · Docker Compose ·
GitHub Actions (tests).

## Project structure

```
src/
  ingestion/   scrapers and box score parser        evaluation/  data validation
  transform/   stable team and player ids           db/          loader
  features/    form over the last N games           models/      live win model code
  api/         FastAPI app                          dashboard/   Streamlit app
  pipeline/    nightly refresh, prediction log, backups
db/            schema, feature views, prediction log
notebooks/     EDA (01-08) and the frozen model (09)
models/        model cards (the fitted .joblib files stay local)
docs/          design and how-to docs
tests/         unit, API, pipeline and dashboard tests (made-up data only)
```
