"""Which model to call and how, for the M1 model check (D3, D8, D9).

Model ID, temperature and effort come from the committed evals/model_check/models.yaml,
so git history proves the settings were fixed before any live run (D9). Only the API
keys come from the environment / .env, and they are only checked for presence: never
read into a message, returned, or logged. The provider client reads them itself.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

Provider = Literal["gemini", "groq"]
# Union of the levels the two providers accept; the provider rejects any it doesn't support.
Effort = Literal["minimal", "low", "medium", "high", "xhigh"]

# Repo root: backend/src/support/llm/config.py -> parents[4]
_REPO_ROOT = Path(__file__).resolve().parents[4]
ENV_FILE = _REPO_ROOT / ".env"
MODELS_FILE = _REPO_ROOT / "evals" / "model_check" / "models.yaml"

KEY_VAR: dict[Provider, str] = {"gemini": "GOOGLE_API_KEY", "groq": "GROQ_API_KEY"}


class ConfigError(Exception):
    """A required setting is missing or invalid. Names the setting, never a key value."""


@dataclass(frozen=True)
class LLMConfig:
    provider: Provider
    model: str
    # None = the provider has no settable temperature, so none is sent (recorded in models.md).
    temperature: float | None
    effort: Effort | None  # None = this model has no effort setting (recorded in models.md)


class _PinnedSettings(BaseModel):
    """One provider's section of models.yaml. Every field must be written out."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    # Both are required keys: write `null` explicitly when the provider has no such setting.
    temperature: float | None = Field(ge=0, le=2)
    effort: Effort | None


def _read_section(provider: Provider, settings_file: Path) -> _PinnedSettings:
    try:
        data = yaml.safe_load(settings_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"Model settings file not found: {settings_file}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"{settings_file.name} is not valid YAML: {exc}") from None
    if not isinstance(data, dict) or provider not in data:
        raise ConfigError(f"No '{provider}' section in {settings_file.name}")
    section = data[provider]
    if isinstance(section, dict) and isinstance(section.get("model"), str):
        section = {**section, "model": section["model"].strip()}
    try:
        return _PinnedSettings.model_validate(section)
    except ValidationError as exc:
        raise ConfigError(f"Invalid '{provider}' section in {settings_file.name}: {exc}") from None


def load_check_config(provider: Provider, settings_file: Path = MODELS_FILE) -> LLMConfig:
    """Pinned settings for one provider. Raises ConfigError naming what is missing."""
    # Values already in the environment win over .env (override=False).
    load_dotenv(ENV_FILE, override=False)
    key_var = KEY_VAR[provider]
    if not os.environ.get(key_var, "").strip():
        raise ConfigError(f"Missing or empty in the environment / .env: {key_var}")
    pinned = _read_section(provider, settings_file)
    return LLMConfig(
        provider=provider,
        model=pinned.model,
        temperature=pinned.temperature,
        effort=pinned.effort,
    )
