.PHONY: setup lint format test up api-up down logs train serve clean validate ids db-up db-down db-reset load psql

# Install dependencies
setup:
	uv sync
	pre-commit install

# Run linter
lint:
	ruff check .

# Auto-format code
format:
	ruff format .
	ruff check --fix .

# Run test suite
test:
	uv run pytest -v

# Start the API and Postgres in Docker, in the background (http://127.0.0.1:8000/docs)
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

# Delete the database and its volume, then start it empty
db-reset:
	docker compose down -v
	docker compose up -d --wait db

# Load the processed CSVs + id tables into Postgres (full refresh, one transaction)
load:
	uv run python -m src.db.load

# Open a SQL prompt on the database (tables are in the `hockey` schema)
psql:
	docker compose exec -e PGOPTIONS="-c search_path=hockey" db psql -U hockey -d hockey

# Build features
features:
	python -m src.features.build_features

# Train a model (usage: make train MODEL=gbm)
train:
	python -m src.models.train --model $(MODEL)

# Run the API at http://127.0.0.1:8000 (docs at /docs). Localhost only: CHN data stays private
serve:
	uv run uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000

# Remove caches, build artifacts
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	rm -rf .ruff_cache
