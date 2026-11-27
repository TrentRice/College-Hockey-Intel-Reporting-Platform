# The public site (free): Streamlit Community Cloud + GitHub

**Live at [chirp-hockey.streamlit.app](https://chirp-hockey.streamlit.app).**

CHIRP's public dashboard runs for free on **Streamlit Community Cloud**. The data lives in a
**private GitHub repo** (`CHIRP-data`), and a **GitHub Actions** job in that repo refreshes it
every morning. No server, and the Mac doesn't need to be on.

**Men's and women's:** the data repo holds the men's at its root and the women's under
`women/`. The nightly job refreshes both, one after the other, and commits each league on
its own terms. The app loads both into its private Postgres (one database each), and the
dashboard's Men | Women switch picks between them. If the women's data fails to load, the
men's site is unaffected.

```
                   PRIVATE: TrentRice/CHIRP-data                       PUBLIC
  ┌───────────────────────────────────────────────────┐
  │ GitHub Actions, every morning:                    │
  │   public code + this repo's data                  │
  │   → scrape → validate → load → predict → backup   │
  │   → commit the results back to this repo          │
  └───────────────────────────────────────────────────┘
               │ read-only token, every ~10 min
               ▼
  Streamlit Community Cloud app (cloud/streamlit_app.py)
    Postgres 18 + CHIRP API, both on 127.0.0.1 inside the app  ──►  the dashboard page
```

- **What's public:** the dashboard page only, with College Hockey News's permission
  ([schema.md](schema.md#data-source-and-use)). It has no login.
- **What isn't:** the data repo (raw pages, tables, prediction log), its Actions logs, and
  the database and API, which run inside the app's container on `127.0.0.1` with a random key.
  The code repo never holds data.
- **Same code everywhere:** the nightly job runs the same pipeline as the Mac
  (`src.pipeline.refresh`), and the app runs the same loader, API and dashboard.

## How it works

**The nightly job** ([deploy/data-repo/.github/workflows/refresh.yml](../deploy/data-repo/.github/workflows/refresh.yml),
copied into the data repo). Three times each morning (5:30, 8:30 and 11:30 a.m. EST, an
hour later in summer), it runs `python -m src.cloud.nightly`
([src/cloud/nightly.py](../src/cloud/nightly.py)), which:
1. **Decides whether a run is due,** with the Mac scheduler's rules: after 5 a.m. Eastern,
   Mondays only May–August, and no retry once today's run succeeded.
2. **Restores the job's memory** into a new, empty Postgres: the run history
   (`pipeline_runs.csv`) and the newest prediction-log backup.
3. **Runs the normal refresh:** scrape, download, parse, validate, ids, load, predict, backup.
4. **Writes the history back** and copies the run's log into `logs/refresh/`.

The workflow then commits to the data repo: **everything** after a success, but **only the
history and logs** after a failure. That way data that failed validation never reaches the
site. A failed run shows red in Actions, and GitHub emails you.

**The app** ([cloud/streamlit_app.py](../cloud/streamlit_app.py) →
[src/cloud/backend.py](../src/cloud/backend.py)). On startup it:
1. downloads `processed/`, `backups/` and `pipeline_runs.csv` from the data repo (never `raw/`),
2. starts Postgres 18 from the `pixeltable-pgserver` wheel, so no system packages are needed,
3. loads the data with `src.db.load`, then the prediction log and the run history,
4. starts the API on `127.0.0.1` in a background thread, then runs the normal dashboard
   (`src/dashboard/app.py`).

Startup takes a few seconds once the dependencies are installed. Every 10 minutes the app asks
GitHub whether the data repo has a new commit, and if so it reloads in the background. A
reload is a full refresh in one transaction, so pages keep working while it runs.

**Postgres in the app:** the bundled build has no `unaccent` extension, so
[db/schema.sql](../db/schema.sql) falls back to a plain `public.unaccent` function for the
API's player-name search. The test suite passes on Postgres 13, 17 and 18.

## Setting it up (once)

### 1. Push the code
The nightly job checks out the public code repo, so the code needs to be on GitHub first:
commit and push as usual.

### 2. Create the data repo (done 2026-11-22)
On the Mac, in the project folder:

```bash
make backup      # the newest prediction log goes along
make data-repo   # builds ../CHIRP-data from data/ (about 150 MB on disk, ~25 MB in git)
```

On GitHub, create a new repository at <https://github.com/new>:
- **Name:** `CHIRP-data`
- **Visibility:** **Private**
- Don't add a README, .gitignore or license (the folder already has them).

Then push it:

```bash
cd ../CHIRP-data
git remote add origin https://github.com/TrentRice/CHIRP-data.git
git push -u origin main
```

### 3. Test the nightly job
In the CHIRP-data repo on GitHub, go to **Actions → Nightly refresh → Run workflow**, tick
**force**, and click **Run workflow**. It takes 5–15 minutes.
- **Green:** check that a new commit, "Nightly refresh … (success)", appeared.
- **Red:** open the run, then the **Refresh** step. If the downloads from College Hockey News
  were refused (403s or timeouts), CHN is blocking GitHub's servers. The fallback is to
  scrape on the Mac and push to the data repo; ask before setting that up.

### 4. Make a read-only token for the app
At <https://github.com/settings/personal-access-tokens/new> (fine-grained token):
- **Name:** `CHIRP Streamlit app (read data)`
- **Expiration:** the longest available. Put a reminder in your calendar to replace it.
- **Repository access:** **Only select repositories** → `CHIRP-data`
- **Permissions → Repository permissions → Contents:** **Read-only** (nothing else)

Click **Generate token** and copy it (it starts with `github_pat_`). It's shown only once.

### 5. Deploy the app
1. Go to <https://share.streamlit.io> and sign in with GitHub.
2. Click **Create app** → **Deploy a public app from GitHub** and fill in:
   - **Repository:** `TrentRice/College-Hockey-Intel-Reporting-Platform`
   - **Branch:** `main`
   - **Main file path:** `cloud/streamlit_app.py`
   - **App URL:** pick a name, e.g. `chirp-hockey` → `https://chirp-hockey.streamlit.app`
3. Open **Advanced settings**, choose **Python 3.12**, and paste this into **Secrets** with
   your token:
   ```toml
   DATA_REPO = "TrentRice/CHIRP-data"
   DATA_REPO_TOKEN = "github_pat_..."
   ```
4. Click **Deploy**. The first build installs the dependencies and takes a few minutes.

### 6. The Mac doesn't scrape anymore
The local Docker stack's `pipeline` service is off by default (a Compose profile), so
`make up` starts only Postgres, the API and the dashboard. For fresh data locally, run
`make data-pull`: it pulls `CHIRP-data`, copies it into `data/`, and loads it.

## Day to day

| To… | Do this |
|---|---|
| See recent refreshes | Data repo → **Actions** (or `pipeline_runs.csv`) |
| Refresh now | Data repo → **Actions → Nightly refresh → Run workflow** |
| Deploy code changes | Push to `main`. Streamlit Cloud pulls the new files into the running app, and the app notices CHIRP's code changed and restarts its backend on the next page view (a few seconds). If a page still shows an error after a push, use **Reboot app** |
| Change dependencies | `uv add …`, then `make cloud-requirements` and commit `cloud/requirements.txt` |
| Change the nightly workflow | Edit `deploy/data-repo/.github/workflows/refresh.yml`, copy it into the data repo, push both |
| Restart the app | share.streamlit.io → the app's **⋮** menu → **Reboot app** |
| Replace the token | Make a new one (step 4), then the app's **Settings → Secrets** |

**Testing the cloud app on the Mac** (Docker, Linux like Streamlit Cloud): build an image from
`python:3.12-slim` that installs `cloud/requirements.txt`, mount the project at `/app` and
`data/` at `/data`, set `CHIRP_DATA_DIR=/data`, and run
`streamlit run cloud/streamlit_app.py`. With `CHIRP_DATA_DIR` set, the app reads that folder
instead of GitHub.

## Limits of the free tier

- **Naps:** an app with no visitors for 12 hours goes to sleep. The next visitor clicks a
  button to wake it, which takes about a minute.
- **Resources:** about 0.7–2.7 GB of memory. CHIRP uses a few hundred MB.
- **Usage statistics:** Streamlit Cloud always turns on Streamlit's anonymous usage statistics,
  whatever `.streamlit/config.toml` says. Locally they stay off.
- **GitHub Actions:** private repos get 2,000 free minutes a month. A nightly run uses
  5–15 minutes, so about 150–450 a month.
- **Data repo size:** about 25 MB now, growing about 10 MB per season. GitHub's comfort limit
  is 1 GB, so there's room for decades.
