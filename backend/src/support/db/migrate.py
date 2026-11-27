"""Applies the numbered .sql files in migrations/, each once, in name order (M2 plan, Task 1).

    uv run python -m support.db.migrate     (from backend/, against DATABASE_URL)

Each applied file's SHA-256 is recorded. If an applied file is edited later, the runner
refuses to start instead of silently skipping the change: a schema change goes in a new
numbered file.
"""

import hashlib
import re
from pathlib import Path
from typing import LiteralString, cast

import psycopg

from support.db.connection import connect, database_url, describe_target

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_NAME = re.compile(r"^\d{3}_[a-z0-9_]+\.sql$")


class MigrationError(Exception):
    """The migration files and the database's record of them don't agree."""


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_migrations(conn: psycopg.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply the files not yet recorded. Returns the file names it applied."""
    files = sorted(migrations_dir.glob("*.sql"))
    for path in files:
        if not _NAME.match(path.name):
            raise MigrationError(f"{path.name}: migration names look like 001_store.sql")
    with conn.transaction():
        conn.execute(
            "CREATE TABLE IF NOT EXISTS public.schema_migrations ("
            " version text PRIMARY KEY,"
            " checksum text NOT NULL,"
            " applied_at timestamptz NOT NULL DEFAULT now())"
        )
    applied = dict(
        conn.execute("SELECT version, checksum FROM public.schema_migrations").fetchall()
    )
    # Check every applied file before applying anything new.
    for path in files:
        if path.name in applied and applied[path.name] != _checksum(path):
            raise MigrationError(
                f"{path.name} was changed after it was applied: put the change in a new file"
            )
    done: list[str] = []
    for path in files:
        if path.name in applied:
            continue
        with conn.transaction():
            # A file holds several statements; psycopg runs them in one call when no
            # parameters are passed. The SQL comes from this repo, never from input.
            conn.execute(cast(LiteralString, path.read_text(encoding="utf-8")))
            conn.execute(
                "INSERT INTO public.schema_migrations (version, checksum) VALUES (%s, %s)",
                (path.name, _checksum(path)),
            )
        done.append(path.name)
    return done


def main() -> int:
    url = database_url()
    with connect(url) as conn:
        done = apply_migrations(conn)
    print(f"migrations on {describe_target(url)}: applied {', '.join(done) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
