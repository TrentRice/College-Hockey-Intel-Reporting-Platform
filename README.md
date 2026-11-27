# CHIRP

**College Hockey Intelligence & Reporting Platform.** A self-updating scouting and
win-probability platform for D-I college hockey, **men's and women's**. For both leagues it
keeps a database of every game, box score and player, serves it through an API and a
scouting dashboard, and predicts every game with a model that's tested against real results.
It was built for scouting Boston University's opponents.

**Live site: [chirp-hockey.streamlit.app](https://chirp-hockey.streamlit.app)**, updated
every morning.

[![CI](https://github.com/TrentRice/College-Hockey-Intel-Reporting-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/TrentRice/College-Hockey-Intel-Reporting-Platform/actions/workflows/ci.yml)

## What it does

Pick a league, **Men or Women**, at the top of the sidebar. Every tab follows it, and the
choice is kept in the link (`?league=women`). The dashboard has seven tabs:

| Tab | What it shows |
|---|---|
| **Team** | The scouted team over its last N games next to its season: 20 stats (19 for women's, no xG share), colored better or worse, and goal differential by game against what the play said (expected goals for men's, shot share for women's, the measure CHN publishes for each) |
| **Players** | Skaters and goalies over the same games, with season numbers alongside, and the likely starting goalie |
| **vs your team** | Both teams side by side on every stat, and this season's meetings |
| **Win probability** | Your team's chance against the next opponent, or any team at a venue you pick, with what drives it |
| **Rankings** | A model "poll": the top 20 by chance to beat an average team on neutral ice, with movement since last week |
| **Model record** | Every prediction, logged before the game and checked against the result: accuracy, log loss, calibration |
| **Acknowledgments** | Credit to College Hockey News for the data, and the terms it's used under |

It defaults to Boston University and its next opponent. The sidebar also picks your team, the
team to scout, a cut-off date ("only games before"), and how many recent games to look at.

## Where it runs

[chirp-hockey.streamlit.app](https://chirp-hockey.streamlit.app) runs free on Streamlit
Community Cloud. The data lives in a private GitHub repo, `CHIRP-data`, and GitHub Actions
refreshes both leagues every morning. Setup and upkeep: [docs/cloud.md](docs/cloud.md).

To run CHIRP on your own computer for development, see [CONTRIBUTING.md](CONTRIBUTING.md).

## How it works

```
                 ┌─ men's ───┐
College Hockey ──┤           ├─► scrape ─► parse ─► validate ─► ids ─► load ─► predict ─► backup
News             └─ women's ─┘                                          │          (nightly, per league)
                                                    Postgres (one database per league)
                                                                        │ read-only
                                                  CHIRP API (?league=men|women) ─► Dashboard
```

**One codebase, two leagues.** Both leagues run through the same scrapers, validation,
loader, API, dashboard and nightly job. Everything that differs between them lives in one
file, [config/leagues.py](config/leagues.py): CHN's page addresses, the data folder, the
database, the win model, and which stats CHN publishes. Each league has its own data, run
history, prediction log and model.

- **Data:**
  - Scrapers collect every D-I team's schedule and every box score: goals, shots by period,
    special teams, skaters, goalies, goals and penalties.
  - A validation gate cross-checks them, 16 exact checks per league. If the numbers don't add
    up, that league's load is skipped and its last good data keeps serving.
  - Stable ids follow players across seasons, spelling changes and transfers. D-I status is
    per season, because programs move up.
- **Database:** PostgreSQL, one database per league, each loaded as a full refresh in one
  transaction.
- **API:** FastAPI with read-only connections and an API key: teams, games, box scores,
  players, leaders, form, win probabilities, rankings and the prediction log, for either
  league (`?league=men` or `?league=women`).
- **Nightly pipeline (GitHub Actions):**
  - Refreshes each league after 5 a.m. Eastern, retries up to twice if it fails, and runs
    weekly in the off-season. Every run is recorded, and a failure emails you.
  - Each league is saved on its own, so one league's failure never blocks the other.
  - Logs each game's win probability before the game, locks it on game day, and backs up
    the prediction log.
- **Public app:** Streamlit Community Cloud. It pulls both leagues from the private repo
  with a read-only token and runs the database and API privately inside the app. Only the
  dashboard page is public. Free apps sleep after 12 hours without a visitor, so a scheduled
  browser visit keeps it awake: 5 minutes after each nightly refresh, and twice more a day.

Details: [architecture](docs/architecture.md) · [database](docs/schema.md) ·
[pipeline](docs/pipeline.md) · [API](docs/api.md) · [dashboard](docs/dashboard.md) ·
[public site](docs/cloud.md) · [form features](docs/features.md) · data validation
([men's](docs/data_validation.md), [women's](docs/data_validation_women.md))

## The win models

Each league has its own model, built by its own analysis under the same method. Nothing is
shared between them except that method, because the two games turned out to reward different
things.

| | Men's (`win_model_v1`) | Women's (`win_model_women_v1`) |
|---|---|---|
| **Inputs** (season to date, home minus away) | Close-game shot share, goal differential | Shots for per game, schedule-adjusted goal differential, PDO |
| **Evenly matched home team wins** | 55.1% | 51.9% |
| **Trained on** | 957 games of 2025-26 | 579 games of 2025-26 |
| **Held-back end of 2025-26** (incl. tournaments) | log loss 0.627, AUC 0.64, 67% | log loss 0.541, AUC 0.78, 74% |
| **2026-27, never seen before** | 173 games: log loss 0.643 vs 0.680 for the home win rate, AUC 0.67, 64% | 244 games: log loss 0.627 vs 0.695 for the home win rate, AUC 0.75, 70% |
| **Rough guide until both teams have** | 3 games | 6 games |
| **Analysis** | [eda.md](docs/eda.md), `notebooks/01`–`09` | [eda_women.md](docs/eda_women.md), `notebooks/women/01`–`09` |
| **Model card** | [model.md](docs/model.md) | [model_women.md](docs/model_women.md) |

**The method, the same for both:**
- **Rules written before results:** each step's rules were fixed in advance
  ([men's](docs/eda_plan.md), [women's](docs/eda_plan_women.md)), scaled to each league's
  sample size.
- **Time-ordered validation:** features were chosen on time-ordered folds of 2025-26, so the
  model is always tested on games after the ones it learned from.
- **Skill before prediction:** each stat was first tested for whether it repeats between a
  team's odd and even games. Luck was set aside before anything was scored.
- **Frozen, then tested once:** each model was frozen and tested on 2026-27 games it had never
  seen. The live code is checked to reproduce the frozen model exactly.
- **Same form:** a regularized logistic regression with a home-ice switch, so neutral-site
  games between equal teams are 50/50. Ties are left out: it's the chance of winning a
  decided game.

**What each league's analysis found:**
- **Shots carry both models.** The season to date beats recent form for every stat in both
  leagues, and rest, back-to-backs and series games add nothing once team strength is known.
- **Women's games are more predictable.** The gaps between women's D-I teams are wider (one
  game in three has a team taking over 60% of the shots), so the same kind of model reaches
  an AUC of 0.75–0.78 against 0.64–0.67 for the men's.
- **Finishing repeats in the women's game.** Shooting % and PDO are partly skill there, and
  PDO enters the women's model as a correction: holding the rest equal, a record built on hot
  shooting or goaltending counts for a little less. In the men's game they were luck.
- **Strength of schedule:** part of the women's model (through the adjusted goal
  differential); tested for the men's but not consistent enough to include yet.

**Limits, for both:** each is weak in a season's first weeks, knows nothing about players
(injuries, a hot goalie), and learned from one season. The live record is on the Model
record tab.

**Next:** v2 for each league carries last season's rating into the first weeks, so
early-season predictions and rankings work from opening night. It's planned for 2027-28,
once 2026-27 is complete.

## Data and privacy

The data comes from [College Hockey News](https://www.collegehockeynews.com), whose terms
allow **personal, non-commercial use only**. So:
- **The data files aren't in this repo:** scraped pages, CSVs, backups and logs are all
  gitignored. They live in a separate **private** repo, refreshed nightly by GitHub Actions
  ([docs/cloud.md](docs/cloud.md)).
- **The analysis is public:** the notebooks are committed with their outputs, tables and
  charts included, with CHN's approval.
- **Only the dashboard is public,** with CHN's permission. The API and databases run
  privately inside the Streamlit app, the API needs a key, and the scrapers respect
  robots.txt.
- **Only 2025-26 onward is kept** (see [docs/schema.md](docs/schema.md#data-source-and-use)).

## Tech stack

Python 3.12, uv · requests, BeautifulSoup/lxml, pandas · PostgreSQL, psycopg ·
FastAPI · Streamlit + Altair · scikit-learn and Jupyter (model building) · GitHub Actions
(tests, nightly refresh) · Streamlit Community Cloud (public site).

## Project structure

```
config/        settings, and leagues.py: everything that differs between the two leagues
src/
  ingestion/   scrapers and box score parser        evaluation/  data validation
  transform/   stable team and player ids           db/          loader
  features/    form over the last N games           models/      live win model code (both models)
  api/         FastAPI app                          dashboard/   Streamlit app
  pipeline/    nightly refresh, prediction log, backups
  cloud/       the public site: nightly job, in-app Postgres + API
cloud/         Streamlit Community Cloud entry point and its requirements
deploy/        the private data repo's workflow and README (source of truth), and its setup script
db/            schema, feature views, prediction log
notebooks/     EDA (01-08) and frozen model (09): men's here, women's in notebooks/women/
models/        model cards, one per league (the fitted .joblib files stay local)
docs/          design and how-to docs
tests/         unit, API, pipeline, dashboard and cloud tests (made-up data only)
```
