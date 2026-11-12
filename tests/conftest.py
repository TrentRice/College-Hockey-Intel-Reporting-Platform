"""Shared fixtures. Database-backed tests use a throwaway `hockey_test` database (see
tests/api/conftest.py) and are skipped when no Postgres is reachable."""

pytest_plugins = ["tests.api.conftest"]
