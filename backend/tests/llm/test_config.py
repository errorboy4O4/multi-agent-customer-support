from pathlib import Path

import pytest

from support.llm import config
from support.llm.config import ConfigError, LLMConfig, load_check_config

KEY_VARS = ["GOOGLE_API_KEY", "GROQ_API_KEY"]

VALID = """\
gemini:
  model: gemini-test-model
  temperature: 1.0
  effort: low
groq:
  model: groq-test-model
  temperature: 0.5
  effort: null
"""


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Never read the developer's real .env in tests, and start from a clean slate.
    monkeypatch.setattr(config, "load_dotenv", lambda *_args, **_kwargs: False)
    for name in KEY_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    monkeypatch.setenv("GROQ_API_KEY", "fake-test-key")


def settings(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_default_settings_file_is_the_committed_one() -> None:
    assert config.MODELS_FILE.parts[-3:] == ("evals", "model_check", "models.yaml")


@pytest.mark.usefixtures("keys")
def test_loads_pinned_settings(tmp_path: Path) -> None:
    path = settings(tmp_path, VALID)
    assert load_check_config("gemini", path) == LLMConfig(
        provider="gemini", model="gemini-test-model", temperature=1.0, effort="low"
    )
    assert load_check_config("groq", path) == LLMConfig(
        provider="groq", model="groq-test-model", temperature=0.5, effort=None
    )


@pytest.mark.usefixtures("keys")
def test_missing_settings_file_names_it(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="models.yaml"):
        load_check_config("gemini", tmp_path / "models.yaml")


@pytest.mark.usefixtures("keys")
def test_missing_provider_section_names_it(tmp_path: Path) -> None:
    path = settings(tmp_path, VALID.split("groq:")[0])
    assert load_check_config("gemini", path).model == "gemini-test-model"
    with pytest.raises(ConfigError, match="groq"):
        load_check_config("groq", path)


@pytest.mark.usefixtures("keys")
@pytest.mark.parametrize(
    ("bad", "named"),
    [
        ("  effort: low\n", "temperature"),  # temperature left out
        ("  temperature: 1.0\n", "effort"),  # effort left out: null must be written explicitly
        ("  temperature: 1.0\n  effort: turbo\n", "effort"),  # not an effort level
        ("  temperature: 3.0\n  effort: low\n", "temperature"),  # outside [0, 2]
        ("  temprature: 1.0\n  temperature: 1.0\n  effort: low\n", "temprature"),  # typo
    ],
)
def test_invalid_settings_name_the_field(tmp_path: Path, bad: str, named: str) -> None:
    path = settings(tmp_path, "gemini:\n  model: gemini-test-model\n" + bad)
    with pytest.raises(ConfigError, match=named):
        load_check_config("gemini", path)


@pytest.mark.usefixtures("keys")
def test_null_temperature_means_send_none(tmp_path: Path) -> None:
    # Written out explicitly: the provider has no settable temperature (e.g. Gemini 3.5).
    path = settings(tmp_path, "gemini:\n  model: m\n  temperature: null\n  effort: medium\n")
    assert load_check_config("gemini", path).temperature is None


@pytest.mark.usefixtures("keys")
def test_empty_model_id_is_refused(tmp_path: Path) -> None:
    path = settings(tmp_path, "gemini:\n  model: ' '\n  temperature: 1.0\n  effort: low\n")
    with pytest.raises(ConfigError, match="model"):
        load_check_config("gemini", path)


def test_missing_key_raises_without_value(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as err:
        load_check_config("gemini", settings(tmp_path, VALID))
    assert "GOOGLE_API_KEY" in str(err.value)


def test_empty_key_counts_as_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # .env.example ships with empty values; a copied-but-unfilled .env must fail clearly.
    monkeypatch.setenv("GROQ_API_KEY", "  ")
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        load_check_config("groq", settings(tmp_path, VALID))


def test_settings_error_never_shows_the_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "sk-SECRET-value-123")
    with pytest.raises(ConfigError) as err:
        load_check_config("gemini", settings(tmp_path, "gemini:\n  model: x\n"))
    assert "SECRET" not in str(err.value)
