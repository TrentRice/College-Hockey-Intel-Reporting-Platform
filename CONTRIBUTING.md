# Working on CHIRP

Notes for future me. The live site is
[chirp-hockey.streamlit.app](https://chirp-hockey.streamlit.app) ([docs/cloud.md](docs/cloud.md)).
This page is for running CHIRP on the Mac to try changes before pushing them: the same
database, API and dashboard in Docker, reachable from this computer only (127.0.0.1).

## First-time setup

```bash
git clone <repo-url> && cd <repo>
git clone https://github.com/TrentRice/CHIRP-data.git ../CHIRP-data   # private: the data
cp .env.example .env     # then set API_KEY (see the comment in the file)
make setup               # installs dependencies
make up                  # Postgres, API and dashboard in Docker
make data-pull           # copies the latest data into data/ and loads it
```

Then open http://127.0.0.1:8501 (dashboard) or http://127.0.0.1:8000/docs (API).

**The data never goes in this repo** (College Hockey News: personal use only). It lives in
the private `CHIRP-data` repo, which GitHub Actions refreshes every morning
([docs/cloud.md](docs/cloud.md)). Run `make data-pull` whenever you want the latest locally.

## Day to day

| Command | What it does |
|---|---|
| `make up` / `make down` | Start / stop the local stack in Docker (data is kept) |
| `make data-pull` | Latest data from the private data repo, loaded into the local database |
| `make logs` | Follow the containers' logs |
| `make refresh` | Scrape CHN from the Mac and load the result (rarely needed: the nightly job does this) |
| `make runs` | Refresh runs recorded in the local database (the nightly job's are in `CHIRP-data`) |
| `make predict` | Log win probabilities for the coming week now |
| `make backup` / `make restore-predictions` | Back up / restore the prediction log |
| `make dashboard` | Dashboard outside Docker, reloading on save (stop the Docker one first) |
| `make serve` | API outside Docker, reloading on save |
| `make psql` | SQL prompt on the database |
| `make test` | All tests (needs `make db-up`; they use a separate made-up test database) |
| `make lint` / `make format` | Ruff |
| `make cloud-requirements` | Regenerate `cloud/requirements.txt` for Streamlit Cloud after a dependency change |

The public site is in [docs/cloud.md](docs/cloud.md): pushing to `main` redeploys it, and the
nightly refresh runs in the `CHIRP-data` repo's **Actions** tab.

## Things that matter

- **Notebooks:** analysis and model building live in `notebooks/`, numbered in order. They're
  committed **with their outputs**, so GitHub shows the tables and charts (College Hockey News
  approved this). Re-run a notebook top to bottom before committing it, so its outputs match
  its code. The data files themselves never go in this repo.
- **The model is frozen.** `models/win_model_v1.json` is v1's card, and v1 never changes. A
  new model is v2, built by the plan in `docs/eda.md`.
- **`make db-reset` deletes the database.** It backs up the prediction log first. Then run
  `make load` and `make restore-predictions`.
- **New dependency:** add it to the group that needs it (`uv add --group api|pipeline|dashboard
  <package>`, or `uv add --dev` for notebooks and tests). Shared ones go in the main list.
  Each Docker image installs only its own group. If the API or dashboard needs it, run
  `make cloud-requirements` too, or the public app won't have it.
- **The nightly workflow has two copies.** The source of truth is
  `deploy/data-repo/.github/workflows/refresh.yml` here. After changing it, copy it into
  `../CHIRP-data/.github/workflows/` and push both repos.
- **Local Docker doesn't scrape.** The `pipeline` service is off by default (a Compose
  profile), so the Mac and GitHub never both hit CHN. Start it only on purpose:
  `docker compose --profile pipeline up -d pipeline`.
- **Commits:** I commit and push myself. Imperative messages ("Add rankings tab").
