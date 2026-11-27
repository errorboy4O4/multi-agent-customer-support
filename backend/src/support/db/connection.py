"""Where the database is, and opening a connection to it (M2 plan, Task 1).

A connection string can carry a password (Neon's always does), so it is never printed
or put in an error message: describe_target() shows user@host:port/db instead.
"""

import os

import psycopg
from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict

from support.llm.config import ENV_FILE, ConfigError


def database_url(var: str = "DATABASE_URL") -> str:
    """The connection string in `var`, from the environment or .env."""
    load_dotenv(ENV_FILE)
    url = os.environ.get(var)
    if not url:
        raise ConfigError(f"{var} is not set: add it to .env (see .env.example)")
    return url


def describe_target(url: str) -> str:
    """user@host:port/dbname, never the password."""
    info = conninfo_to_dict(url)
    port = info.get("port") or "5432"
    return f"{info.get('user')}@{info.get('host')}:{port}/{info.get('dbname')}"


def require_test_database(url: str) -> str:
    """Refuse any database whose name doesn't end in _test, so tests can't wipe real data."""
    dbname = str(conninfo_to_dict(url).get("dbname") or "")
    if not dbname.endswith("_test"):
        raise ConfigError(f"tests only run against a *_test database, not {describe_target(url)}")
    return url


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url)
