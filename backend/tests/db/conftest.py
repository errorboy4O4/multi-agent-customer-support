"""Database fixtures (M2 plan, Task 1).

Tests only ever touch a database whose name ends in _test. Without TEST_DATABASE_URL
the database tests skip locally, but fail when REQUIRE_DB=1 (CI sets it), so a missing
database can never pass CI as a skip.
"""

import os
from collections.abc import Iterator

import psycopg
import pytest
from dotenv import dotenv_values

from support.db.connection import connect, require_test_database
from support.db.migrate import apply_migrations
from support.llm.config import ENV_FILE


def _test_db_url() -> str | None:
    # dotenv_values reads .env without copying anything (such as API keys) into os.environ.
    return os.environ.get("TEST_DATABASE_URL") or dotenv_values(ENV_FILE).get("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def db_url() -> str:
    url = _test_db_url()
    if not url:
        if os.environ.get("REQUIRE_DB") == "1":
            pytest.fail("REQUIRE_DB=1 but TEST_DATABASE_URL is not set")
        pytest.skip("TEST_DATABASE_URL is not set: database tests skipped")
    return require_test_database(url)


@pytest.fixture(scope="session")
def fresh_db(db_url: str) -> str:
    """Drop both schemas and the migrations table, then apply every migration."""
    with connect(db_url) as conn:
        conn.autocommit = True
        conn.execute("DROP SCHEMA IF EXISTS store CASCADE")
        conn.execute("DROP SCHEMA IF EXISTS log CASCADE")
        conn.execute("DROP TABLE IF EXISTS public.schema_migrations")
        apply_migrations(conn)
    return db_url


@pytest.fixture
def conn(fresh_db: str) -> Iterator[psycopg.Connection]:
    """A connection inside a transaction that is always rolled back."""
    with connect(fresh_db) as c, c.transaction(force_rollback=True):
        yield c
