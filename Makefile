.PHONY: cloud-requirements data-repo data-pull setup lint format test up api-up down logs refresh predict backup restore-predictions runs dashboard serve clean validate ids db-up db-down db-reset load psql

# First-time setup: install every dependency group, and strip notebook outputs from git
# (CHN data must never be committed; nbstripout's filter lives in .git/config, so a fresh
# clone needs it again)
setup:
	uv sync
	uv run nbstripout --install --attributes .gitattributes

# Lint and auto-format (ruff runs through uvx; it isn't a project dependency)
lint:
	uvx ruff check .

format:
	uvx ruff format .
	uvx ruff check --fix .

# Run test suite
test:
	uv run pytest -v

# Start Postgres, the API and the dashboard in Docker (local development; the nightly refresh
# runs in GitHub Actions, docs/cloud.md). Then `make data-pull` loads the latest data.
#   dashboard: http://127.0.0.1:8501   API docs: http://127.0.0.1:8000/docs
up api-up:
	docker compose up -d --build --wait

# Stop the stack (data is kept in the pgdata volume)
down:
	docker compose down

# Tail logs from the stack
logs:
	docker compose logs -f

# --- Streamlit Community Cloud (docs/cloud.md) ---------------------------------------------
# Regenerate cloud/requirements.txt after changing dependencies (Streamlit Cloud installs it)
cloud-requirements:
	{ echo "# Streamlit Community Cloud dependencies (docs/cloud.md): the api, dashboard and cloud"; \
	  echo "# groups. Generated from uv.lock by \`make cloud-requirements\`; don't edit by hand."; \
	  uv export --locked --no-default-groups --group api --group dashboard --group cloud \
	    --no-hashes --no-header --no-annotate --no-emit-project; } > cloud/requirements.txt

# Where the private data repo is cloned (docs/cloud.md)
DATA_REPO ?= ../CHIRP-data

# Get the latest data from the private data repo into data/ and load it into the local
# database: the tables, then the prediction log exactly as the nightly job left it
data-pull: db-up
	git -C "$(DATA_REPO)" pull -q
	rsync -a --exclude .gitkeep "$(DATA_REPO)/raw/" data/raw/
	rsync -a --delete --exclude .gitkeep --exclude validation/ "$(DATA_REPO)/processed/" data/processed/
	rsync -a "$(DATA_REPO)/backups/" data/backups/
	uv run python -m src.db.load
	uv run python -m src.pipeline.backup --restore --replace

# One time only, already done: build the data repo's first version from data/
data-repo:
	deploy/make-data-repo.sh $(DATA_REPO)

# Run data ingestion
ingest:
	python -m src.ingestion.load_data

# Validate the processed CHN data and regenerate docs/data_validation.md
validate:
	uv run python -m src.evaluation.validate_chn_data --strict

# Assign stable team/player ids (data/processed/ids/); reuses ids from the last run
ids:
	uv run python -m src.transform.id_mapping

# Start the Postgres database in Docker (waits until it accepts connections)
db-up:
	docker compose up -d --wait db

# Stop the database (data is kept in the pgdata volume)
db-down:
	docker compose stop db

# Delete the database and its volume, then start it empty. Backs up the prediction log
# first (it can't be rebuilt from CHN) and stops if that fails; FORCE=1 skips the backup.
# Afterwards: `make load`, then `make restore-predictions`.
db-reset:
	@if [ -z "$(FORCE)" ]; then uv run python -m src.pipeline.backup || { echo "Backup failed, so the database was NOT reset. Fix it, or run 'make db-reset FORCE=1'."; exit 1; }; fi
	docker compose down -v
	docker compose up -d --wait db
	@echo "Database reset. Next: make load, then make restore-predictions"

# Load the processed CSVs + id tables into Postgres (full refresh, one transaction)
load:
	uv run python -m src.db.load

# Open a SQL prompt on the database (tables are in the `hockey` schema)
psql:
	docker compose exec -e PGOPTIONS="-c search_path=hockey" db psql -U hockey -d hockey

# Refresh the local data by scraping CHN from this Mac: scrape, download, parse, validate, ids,
# load. Rarely needed: GitHub Actions refreshes nightly, and `make data-pull` gets the result
refresh:
	uv run python -m src.pipeline.refresh

# Log win probabilities for the coming week (the nightly refresh does this after the load)
predict:
	uv run python -m src.pipeline.predict

# Back up the prediction log to data/backups/ (the nightly refresh does this too)
backup:
	uv run python -m src.pipeline.backup

# Add rows from the newest backup (or FILE=data/backups/predictions_YYYY-MM-DD.csv.gz)
# that aren't in the prediction log; never overwrites
restore-predictions:
	uv run python -m src.pipeline.backup --restore $(FILE)

# Recent refresh runs
runs:
	docker compose exec -T db psql -U hockey -d hockey -P pager=off -c "SET timezone = 'America/New_York'; SELECT run_id, started_at::timestamp(0) AS started_eastern, date_trunc('second', finished_at - started_at) AS took, status, trigger, failed_step, played_after - played_before AS new_games FROM ops.pipeline_runs ORDER BY run_id DESC LIMIT 10"

# Run the dashboard outside Docker (reloads on save): http://127.0.0.1:8501
# Stop the Docker one first (`docker compose stop dashboard`): both use port 8501
dashboard:
	uv run python -m streamlit run src/dashboard/app.py --server.address 127.0.0.1

# Build features
features:
	python -m src.features.build_features


# Run the API at http://127.0.0.1:8000 (docs at /docs). Localhost only: CHN data stays private
serve:
	uv run uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000

# Remove caches, build artifacts
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	rm -rf .ruff_cache
