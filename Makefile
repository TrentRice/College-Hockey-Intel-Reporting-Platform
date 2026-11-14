.PHONY: setup lint format test up api-up down logs refresh predict backup restore-predictions runs dashboard serve clean validate ids db-up db-down db-reset load psql

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

# Start Postgres, the API, the nightly refresh and the dashboard in Docker
#   dashboard: http://127.0.0.1:8501   API docs: http://127.0.0.1:8000/docs
up api-up:
	docker compose up -d --build --wait

# Stop the stack (data is kept in the pgdata volume)
down:
	docker compose down

# Tail logs from the stack
logs:
	docker compose logs -f

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

# Refresh the data now: scrape, download, parse, validate, ids, load (also runs nightly in Docker)
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
	uv run python -m streamlit run src/dashboard/app.py

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
