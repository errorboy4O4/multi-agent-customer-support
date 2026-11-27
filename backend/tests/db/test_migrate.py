from pathlib import Path

import psycopg
import pytest

from support.db.migrate import MigrationError, apply_migrations

pytestmark = pytest.mark.db


def _write(folder: Path, name: str, sql: str) -> None:
    (folder / name).write_text(sql, encoding="utf-8")


def test_migrations_apply_in_order_once(conn: psycopg.Connection, tmp_path: Path) -> None:
    # 002 depends on 001's table, so applying them out of order would fail.
    _write(tmp_path, "002_b.sql", "INSERT INTO mig_probe (x) VALUES (2);")
    _write(tmp_path, "001_a.sql", "CREATE TABLE mig_probe (x int);")
    assert apply_migrations(conn, tmp_path) == ["001_a.sql", "002_b.sql"]
    assert apply_migrations(conn, tmp_path) == []
    rows = conn.execute("SELECT x FROM mig_probe").fetchall()
    assert rows == [(2,)]


def test_changed_applied_migration_is_refused(conn: psycopg.Connection, tmp_path: Path) -> None:
    _write(tmp_path, "001_a.sql", "CREATE TABLE mig_probe (x int);")
    apply_migrations(conn, tmp_path)
    _write(tmp_path, "001_a.sql", "CREATE TABLE mig_probe (x bigint);")
    with pytest.raises(MigrationError, match="001_a.sql"):
        apply_migrations(conn, tmp_path)
