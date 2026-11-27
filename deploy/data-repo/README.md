# CHIRP data (private)

The data behind CHIRP's public dashboard, men's and women's: scraped College Hockey News
pages, the processed tables, the prediction logs and the refresh history. **Men's files are at
the root; women's mirror them under `women/`.** **Keep this repo private.** CHN allows
personal use only, and its permission covers the public dashboard, not this data.

How it's used is documented in the code repo, `docs/cloud.md`:

- **Nightly:** `.github/workflows/refresh.yml` refreshes the men's, then the women's, and
  commits each league here on its own terms (a failed league saves only its history and logs).
- **The dashboard** (Streamlit Community Cloud) downloads each league's `processed/`,
  `backups/` and `pipeline_runs.csv` with a read-only token, never `raw/`.

| Path | What it is |
|---|---|
| `raw/chn/` | Downloaded schedule and box score pages. Keep them: CHN's robots.txt closes older seasons' pages, so they can't always be downloaded again |
| `processed/chn/`, `processed/ids/` | The tables the database is loaded from, and the stable team and player ids |
| `backups/` | Prediction-log backups. The log can't be rebuilt from CHN |
| `pipeline_runs.csv` | Every refresh: when, how it went, how many new games |
| `logs/refresh/` | Each run's log and validation report |
| `women/` | The same layout for the women's league |

To run a refresh now: **Actions → Nightly refresh → Run workflow**.
