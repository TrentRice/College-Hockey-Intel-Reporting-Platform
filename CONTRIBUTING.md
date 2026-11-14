# Working on CHIRP

Notes for future me.

## First-time setup

```bash
git clone <repo-url> && cd <repo>
cp .env.example .env     # then set API_KEY (see the comment in the file)
make setup               # installs dependencies; turns on notebook output stripping
make up                  # Postgres, API, nightly pipeline and dashboard in Docker
```

The database starts empty. The first `make refresh`, or the first nightly run, scrapes CHN
and loads it. **The data never goes in git** (College Hockey News: personal use only).

## Day to day

| Command | What it does |
|---|---|
| `make up` / `make down` | Start / stop everything in Docker (data is kept) |
| `make logs` | Follow the containers' logs |
| `make refresh` | Run the full data refresh now (normally nightly) |
| `make runs` | Recent refresh runs and their status |
| `make predict` | Log win probabilities for the coming week now |
| `make backup` / `make restore-predictions` | Back up / restore the prediction log |
| `make dashboard` | Dashboard outside Docker, reloading on save (stop the Docker one first) |
| `make serve` | API outside Docker, reloading on save |
| `make psql` | SQL prompt on the database |
| `make test` | All tests (needs `make db-up`; they use a separate made-up test database) |
| `make lint` / `make format` | Ruff |

## Things that matter

- **Notebooks:** analysis and model building live in `notebooks/`, numbered in order. Their
  outputs are stripped on commit (CHN data). After a fresh clone, `make setup` turns that
  back on.
- **The model is frozen.** `models/win_model_v1.json` is v1's card, and v1 never changes. A
  new model is v2, built by the plan in `docs/eda.md`.
- **`make db-reset` deletes the database.** It backs up the prediction log first. Then run
  `make load` and `make restore-predictions`.
- **New dependency:** add it to the group that needs it (`uv add --group api|pipeline|dashboard
  <package>`, or `uv add --dev` for notebooks and tests). Shared ones go in the main list.
  Each Docker image installs only its own group.
- **Commits:** I commit and push myself. Imperative messages ("Add rankings tab").
