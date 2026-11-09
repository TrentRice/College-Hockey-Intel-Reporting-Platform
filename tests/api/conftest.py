"""API tests run against a throwaway `hockey_test` database holding made-up rows
(tests/api/fixture.sql), never the real data. Skipped when no Postgres is reachable.

Override the server with TEST_DATABASE_URL (CI points it at a Postgres service container).
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://hockey:hockey@localhost:5432/hockey_test"
)
API_KEY = "test-key"
SCHEMA_SQL = Path("db/schema.sql")
FIXTURE_SQL = Path(__file__).with_name("fixture.sql")


def ensure_database(url: str) -> None:
    """Create the test database if the server is up but the database isn't there yet."""
    try:
        psycopg.connect(url, connect_timeout=2).close()
        return
    except psycopg.OperationalError as e:
        if "does not exist" not in str(e):
            pytest.skip(f"No Postgres for API tests ({e}). Start it with `make db-up`.")
    info = psycopg.conninfo.conninfo_to_dict(url)
    name = info.pop("dbname")
    admin = psycopg.conninfo.make_conninfo(**info, dbname="postgres")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')


@pytest.fixture(scope="session")
def database_url() -> str:
    ensure_database(TEST_DATABASE_URL)
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        conn.execute("DROP SCHEMA IF EXISTS hockey CASCADE")
        conn.execute(SCHEMA_SQL.read_text())
        conn.execute(FIXTURE_SQL.read_text())
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def client(database_url: str):
    with TestClient(create_app(database_url=database_url, api_key=API_KEY)) as c:
        c.headers["X-API-Key"] = API_KEY
        yield c
