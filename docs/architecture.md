# Architecture

How CHIRP fits together. On the Mac, the whole stack runs in Docker, and every port listens
on 127.0.0.1 only. The public site runs the same code for free ([cloud.md](cloud.md)): the
nightly refresh in GitHub Actions in a private data repo, and the database, API and dashboard
inside one Streamlit Community Cloud app, where only the dashboard page is public (with
College Hockey News's permission).

```
College Hockey News (schedules, box scores)
        │  nightly, src/pipeline/scheduler.py  ─────────────────────────────┐
        ▼                                                                    │
scrape ─► parse ─► validate (gate) ─► ids ─► load ─► predict ─► backup       │ pipeline
        │                                    │         │          │          │ container
        ▼                                    ▼         ▼          ▼          │
data/raw, data/processed (CSV)      Postgres  hockey   predictions  data/backups
(gitignored, on this Mac)           schemas:  features (prediction  (gitignored)
                                              ops       log)
                                        │
                                        ▼  read-only connections
                                   CHIRP API (FastAPI)  ──  X-API-Key  ──  127.0.0.1:8000
                                        │
                                        ▼
                                   Dashboard (Streamlit)  ──────────────  127.0.0.1:8501
```

The public site ([cloud.md](cloud.md)) splits the same pieces in two:

```
private data repo (GitHub)                        Streamlit Community Cloud app
  nightly Actions job: the pipeline above   ──►     Postgres + API on 127.0.0.1  ──►  public page
  data/ committed after each good run      token      (src/cloud/backend.py)
```

## Pieces

| Piece | Code | Docs |
|---|---|---|
| Scrapers, parser, validation | `src/ingestion/`, `src/evaluation/` | [data_validation.md](data_validation.md) |
| Stable team and player ids | `src/transform/id_mapping.py` | [schema.md](schema.md) |
| Database and loader | `db/schema.sql`, `db/features.sql`, `src/db/load.py` | [schema.md](schema.md) |
| Nightly refresh, prediction log, backups | `src/pipeline/`, `src/cloud/nightly.py` | [pipeline.md](pipeline.md) |
| Public site: GitHub Actions job, Streamlit app | `src/cloud/`, `cloud/`, `deploy/data-repo/` | [cloud.md](cloud.md) |
| Form features (last N games) | `src/features/form.py` | [features.md](features.md) |
| Win model v1 (live predictions, rankings) | `src/models/win_model.py`, `models/win_model_v1.json` | [model.md](model.md) |
| API | `src/api/` | [api.md](api.md) |
| Dashboard | `src/dashboard/` | [dashboard.md](dashboard.md) |
| EDA and model building (notebooks) | `notebooks/01`–`09` | [eda_plan.md](eda_plan.md), [eda.md](eda.md) |

## Decisions worth knowing

- **Two leagues, one codebase.** Men's and women's share every step: scrapers, validation,
  loader, API, dashboard and nightly job. Everything that differs lives in
  [config/leagues.py](../config/leagues.py): CHN's URL prefix and team links, the data
  folder, the database, the model card, and whether xG and skater ice time exist. Each league
  has its own frozen model, built from scratch by its own EDA (men's
  [eda.md](eda.md), women's [eda_women.md](eda_women.md)).
- **D-I status is per season** (`team_seasons.is_d1`): programs move up (four women's ones
  did in 2026-27), and a past season's games must use that season's status.
- **Postgres, one database with separate schemas.** It's in Docker on the Mac; in the cloud,
  each nightly job and each app start gets a fresh one, filled from the private data repo:
  - **`hockey`:** the data, rebuilt in full by every load, in one transaction.
  - **`features`:** views over `hockey`.
  - **`ops`:** refresh run history.
  - **`predictions`:** the prediction log, which no load touches and which is backed up
    nightly.
- **The dashboard only talks to the API, and the API only reads.** Connections are
  read-only, so no endpoint can change data.
- **Validation is a gate.** If CHN's numbers don't add up, the load is skipped and the last
  good data keeps serving.
- **No data in this repo.** CSVs, raw pages, backups and logs live in the private
  `CHIRP-data` repo (and in `data/` on the Mac, gitignored). Notebooks are committed with
  their outputs, which College Hockey News approved. The model card JSON holds coefficients
  only.
- **The public site runs the same code.** The nightly job calls the same refresh, and the
  Streamlit app runs the same loader, API and dashboard. Only the glue differs:
  `src/cloud/`.
- **Notebooks build the model, Python modules serve it.** Notebook 09 checks that the live
  code (`src/models/win_model.py`) reproduces the frozen model exactly.
- **One Dockerfile, three images** (local development):
  - **api:** FastAPI and psycopg only.
  - **pipeline:** scrapers and pandas.
  - **dashboard:** Streamlit.

  Each installs only its own dependency group from `pyproject.toml`.
