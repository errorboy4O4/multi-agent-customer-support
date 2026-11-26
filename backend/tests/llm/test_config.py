import pytest

from support.llm import config
from support.llm.config import ConfigError, LLMConfig, load_check_config

ALL_VARS = ["GOOGLE_API_KEY", "GROQ_API_KEY", "CHECK_GEMINI_MODEL", "CHECK_GROQ_MODEL"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Never read the developer's real .env in tests, and start from a clean slate.
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: False)
    for name in ALL_VARS:
        monkeypatch.delenv(name, raising=False)


def test_loads_gemini_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHECK_GEMINI_MODEL", "gemini-test-model")
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    assert load_check_config("gemini") == LLMConfig(
        provider="gemini", model="gemini-test-model", temperature=None
    )


def test_loads_groq_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHECK_GROQ_MODEL", "groq-test-model")
    monkeypatch.setenv("GROQ_API_KEY", "fake-test-key")
    assert load_check_config("groq").model == "groq-test-model"


def test_missing_model_var_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "sk-SECRET-value-123")
    with pytest.raises(ConfigError) as err:
        load_check_config("gemini")
    assert "CHECK_GEMINI_MODEL" in str(err.value)
    # The key is set, so it must not be named, and its value must never appear.
    assert "GOOGLE_API_KEY" not in str(err.value)
    assert "SECRET" not in str(err.value)


def test_missing_key_raises_without_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHECK_GEMINI_MODEL", "gemini-test-model")
    with pytest.raises(ConfigError) as err:
        load_check_config("gemini")
    assert "GOOGLE_API_KEY" in str(err.value)


def test_empty_values_count_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # .env.example ships with empty values; a copied-but-unfilled .env must fail clearly.
    monkeypatch.setenv("CHECK_GROQ_MODEL", "")
    monkeypatch.setenv("GROQ_API_KEY", "  ")
    with pytest.raises(ConfigError) as err:
        load_check_config("groq")
    assert "CHECK_GROQ_MODEL" in str(err.value)
    assert "GROQ_API_KEY" in str(err.value)
