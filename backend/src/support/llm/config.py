"""Which model to call, read from the environment (D8, D9).

Key values are only checked for presence here. They are never read into a message,
returned, or logged; the provider client reads them from the environment itself.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

Provider = Literal["gemini", "groq"]

# Repo root: backend/src/support/llm/config.py -> parents[4]
ENV_FILE = Path(__file__).resolve().parents[4] / ".env"

_MODEL_VAR: dict[Provider, str] = {"gemini": "CHECK_GEMINI_MODEL", "groq": "CHECK_GROQ_MODEL"}
KEY_VAR: dict[Provider, str] = {"gemini": "GOOGLE_API_KEY", "groq": "GROQ_API_KEY"}


class ConfigError(Exception):
    """A required setting is missing or invalid. Names the setting, never a value."""


@dataclass(frozen=True)
class LLMConfig:
    provider: Provider
    model: str
    # None = send no temperature, so the provider's own default applies.
    temperature: float | None


def _is_set(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def load_check_config(provider: Provider) -> LLMConfig:
    """Config for the M1 model check. Raises ConfigError naming every missing variable."""
    # Values already in the environment win over .env (override=False).
    load_dotenv(ENV_FILE, override=False)
    model_var, key_var = _MODEL_VAR[provider], KEY_VAR[provider]
    missing = [name for name in (model_var, key_var) if not _is_set(name)]
    if missing:
        raise ConfigError(f"Missing or empty in the environment / .env: {', '.join(missing)}")
    return LLMConfig(provider=provider, model=os.environ[model_var].strip(), temperature=None)
