# Architecture

How CHIRP fits together. Everything runs on one Mac, and every port listens on 127.0.0.1
only, because College Hockey News allows personal, non-commercial use only.

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

## Pieces

| Piece | Code | Docs |
|---|---|---|
| Scrapers, parser, validation | `src/ingestion/`, `src/evaluation/` | [data_validation.md](data_validation.md) |
| Stable team and player ids | `src/transform/id_mapping.py` | [schema.md](schema.md) |
| Database and loader | `db/schema.sql`, `db/features.sql`, `src/db/load.py` | [schema.md](schema.md) |
| Nightly refresh, prediction log, backups | `src/pipeline/` | [pipeline.md](pipeline.md) |
| Form features (last N games) | `src/features/form.py` | [features.md](features.md) |
| Win model v1 (live predictions, rankings) | `src/models/win_model.py`, `models/win_model_v1.json` | [model.md](model.md) |
| API | `src/api/` | [api.md](api.md) |
| Dashboard | `src/dashboard/` | [dashboard.md](dashboard.md) |
| EDA and model building (notebooks) | `notebooks/01`–`09` | [eda_plan.md](eda_plan.md), [eda.md](eda.md) |

## Decisions worth knowing

- **Postgres in Docker, one database with separate schemas:**
  - **`hockey`:** the data, rebuilt in full by every load, in one transaction.
  - **`features`:** views over `hockey`.
  - **`ops`:** refresh run history.
  - **`predictions`:** the prediction log, which no load touches and which is backed up
    nightly.
- **The dashboard only talks to the API, and the API only reads.** Connections are
  read-only, so no endpoint can change data.
- **Validation is a gate.** If CHN's numbers don't add up, the load is skipped and the last
  good data keeps serving.
- **No data in git.** CSVs, raw pages, backups and notebook outputs (stripped by
  nbstripout) stay on this Mac. The model card JSON holds coefficients only.
- **Notebooks build the model, Python modules serve it.** Notebook 09 checks that the live
  code (`src/models/win_model.py`) reproduces the frozen model exactly.
- **One Dockerfile, three images:**
  - **api:** FastAPI and psycopg only.
  - **pipeline:** scrapers and pandas.
  - **dashboard:** Streamlit.

  Each installs only its own dependency group from `pyproject.toml`.
