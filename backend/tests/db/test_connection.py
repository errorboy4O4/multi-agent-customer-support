import pytest

from support.db import connection
from support.db.connection import database_url, describe_target, require_test_database
from support.llm.config import ConfigError


def test_database_url_missing_names_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Never read the developer's real .env in tests.
    monkeypatch.setattr(connection, "load_dotenv", lambda *_args, **_kwargs: False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    with pytest.raises(ConfigError, match="TEST_DATABASE_URL"):
        database_url("TEST_DATABASE_URL")


def test_describe_target_hides_password() -> None:
    described = describe_target("postgresql://u:secret@h:5432/d_test")
    assert described == "u@h:5432/d_test"
    assert "secret" not in described


def test_guard_refuses_non_test_database() -> None:
    with pytest.raises(ConfigError, match="_test"):
        require_test_database("postgresql://u:p@localhost:5433/support_dev")
    ok = "postgresql://u:p@localhost:5433/support_test"
    assert require_test_database(ok) == ok
