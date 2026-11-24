# CHIRP

**College Hockey Intelligence & Reporting Platform.** A self-updating platform for
D-I men's college hockey. It has a database of every game, box score and player, an API, a
scouting dashboard, and a win-probability model that's tested against real results. It was
built for scouting Boston University's opponents.

**Live site: [chirp-hockey.streamlit.app](https://chirp-hockey.streamlit.app)**, updated
every morning.

[![CI](https://github.com/TrentRice/College-Hockey-Intel-Reporting-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/TrentRice/College-Hockey-Intel-Reporting-Platform/actions/workflows/ci.yml)

## What it does

The dashboard at [chirp-hockey.streamlit.app](https://chirp-hockey.streamlit.app) has seven
tabs:

| Tab | What it shows |
|---|---|
| **Team** | The scouted team over its last N games next to its season: 20 stats, colored better or worse, and actual vs. expected goal differential by game |
| **Players** | Skaters and goalies over the same games, with season numbers alongside, and the likely starting goalie |
| **vs your team** | Both teams side by side on every stat, and this season's meetings |
| **Win probability** | Your team's chance against the next opponent, or any team at a venue you pick, with what drives it |
| **Rankings** | A model "poll": the top 20 by chance to beat an average team on neutral ice, with movement since last week |
| **Model record** | Every prediction, logged before the game and checked against the result: accuracy, log loss, calibration |
| **Acknowledgments** | Credit to College Hockey News for the data, and the terms it's used under |

It defaults to BU and its next opponent. The sidebar picks your team, the team to scout, a
cut-off date ("only games before"), and how many recent games to look at.

## Where it runs

[chirp-hockey.streamlit.app](https://chirp-hockey.streamlit.app) runs free on Streamlit
Community Cloud. The data lives in a private GitHub repo, `CHIRP-data`, and GitHub Actions
refreshes it every morning. Setup and upkeep: [docs/cloud.md](docs/cloud.md).

To run CHIRP on your own computer for development, see [CONTRIBUTING.md](CONTRIBUTING.md).

## How it works

```
College Hockey News ─► scrape ─► parse ─► validate ─► ids ─► load ─► predict ─► backup   (nightly)
                                                              │
                                     Postgres ◄────────────────┘
                                        │ read-only
                                     CHIRP API (key required) ─► Dashboard
```

On the public site, the nightly steps run in GitHub Actions and commit the results to the
private data repo. The Streamlit app loads them into its own Postgres and runs the same API
and dashboard inside the app ([docs/cloud.md](docs/cloud.md)).

- **Data:**
  - Scrapers collect every D-I team's schedule and every box score: goals, shots by period,
    special teams, skaters, goalies, goals and penalties.
  - A validation gate cross-checks them. If the numbers don't add up, the load is skipped
    and the last good data keeps serving.
  - Stable ids follow players across seasons, spelling changes and transfers.
- **Database:** PostgreSQL, loaded as a full refresh in one transaction.
- **API:** FastAPI with read-only connections and an API key. It covers teams, games, box
  scores, players, leaders, form, win probabilities, rankings and the prediction log.
- **Nightly pipeline (GitHub Actions):**
  - Runs after 5 a.m. Eastern, retries up to twice if it fails, and runs weekly in the
    off-season. Every run is recorded, and a failure emails you.
  - Logs each game's win probability before the game and locks it on game day.
  - Backs up the prediction log, and commits everything to the private data repo only if
    validation passed.
- **Public app:** Streamlit Community Cloud, with the data pulled from the private repo with a
  read-only token. Only the dashboard page is public. An idle app naps after 12 hours, and
  the next visitor wakes it in about a minute.

Details: [architecture](docs/architecture.md) · [database](docs/schema.md) ·
[pipeline](docs/pipeline.md) · [API](docs/api.md) · [dashboard](docs/dashboard.md) ·
[public site](docs/cloud.md) ·
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

**Limits:**
- **Weak in a season's first weeks.**
- **Not adjusted for strength of schedule.** It was tested, but with one season of data it
  didn't help consistently (better in only 2 of 4 test folds). So it's left out for now, and
  it's the first thing to revisit in v2.
- **Knows nothing about players.**

Full card: [docs/model.md](docs/model.md).

**Next:** v2 carries last season over, so early-season predictions and rankings work from
opening night. It's planned for 2027-28, once 2026-27 is complete (plan in
[docs/eda.md](docs/eda.md)).

## Data and privacy

The data comes from [College Hockey News](https://www.collegehockeynews.com), whose terms
allow **personal, non-commercial use only**. So:
- **The data files aren't in this repo:** scraped pages, CSVs, backups and logs are all
  gitignored. They live in a separate **private** repo, refreshed nightly by GitHub Actions
  ([docs/cloud.md](docs/cloud.md)).
- **The analysis is public:** the notebooks are committed with their outputs, tables and
  charts included, with CHN's approval.
- **Only the dashboard is public,** with CHN's permission. The API and database run privately
  inside the Streamlit app, the API needs a key, and the scrapers respect robots.txt.
- **Only 2025-26 onward is kept** (see [docs/schema.md](docs/schema.md#data-source-and-use)).

## Tech stack

Python 3.12, uv · requests, BeautifulSoup/lxml, pandas · PostgreSQL, psycopg ·
FastAPI · Streamlit + Altair · scikit-learn and Jupyter (model building) · GitHub Actions
(tests, nightly refresh) · Streamlit Community Cloud (public site).

## Project structure

```
src/
  ingestion/   scrapers and box score parser        evaluation/  data validation
  transform/   stable team and player ids           db/          loader
  features/    form over the last N games           models/      live win model code
  api/         FastAPI app                          dashboard/   Streamlit app
  pipeline/    nightly refresh, prediction log, backups
  cloud/       the public site: nightly job, in-app Postgres + API
cloud/         Streamlit Community Cloud entry point and its requirements
deploy/        the private data repo's workflow and README (source of truth), and its setup script
db/            schema, feature views, prediction log
notebooks/     EDA (01-08) and the frozen model (09)
models/        model cards (the fitted .joblib files stay local)
docs/          design and how-to docs
tests/         unit, API, pipeline, dashboard and cloud tests (made-up data only)
```
