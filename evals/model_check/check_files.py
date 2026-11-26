"""Loads the M1 check files: cases.yaml, conversations.yaml and system_prompt.md.

Every file is validated when it loads, so a typo in a case fails here, before any live
run spends quota. Task 7's runner and the load test both read the files through this.
"""

from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from evals.model_check.scoring import CheckCase
from support.tools.schemas import TOOL_SPECS

CHECK_DIR = Path(__file__).resolve().parent
CASES_FILE = CHECK_DIR / "cases.yaml"
CONVERSATIONS_FILE = CHECK_DIR / "conversations.yaml"
PROMPT_FILE = CHECK_DIR / "system_prompt.md"


class CannedResult(BaseModel):
    """What a tool "returns" in a conversation when a call's args contain `args_match`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: str
    args_match: dict[str, Any]
    result: dict[str, Any]

    @model_validator(mode="after")
    def _known_tool_and_args(self) -> Self:
        spec = TOOL_SPECS.get(self.tool)
        if spec is None:
            raise ValueError(f"canned result for {self.tool!r}, which is not one of the D7 tools")
        unknown = set(self.args_match) - set(spec.model_fields)
        if unknown:
            raise ValueError(f"args_match has names {self.tool} lacks: {unknown}")
        return self


class Conversation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    lang: Literal["en", "hinglish"]
    turns: list[str] = Field(min_length=2, max_length=4)
    canned: list[CannedResult]


def _load_list(path: Path, key: str) -> list[Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        raise ValueError(f"{path.name} must have a top-level '{key}' list")
    return data[key]


def _unique_ids(items: list[CheckCase] | list[Conversation], name: str) -> None:
    ids = [i.id for i in items]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate ids in {name}: {sorted(dupes)}")


def load_cases(path: Path = CASES_FILE) -> list[CheckCase]:
    cases = [CheckCase.model_validate(c) for c in _load_list(path, "cases")]
    _unique_ids(cases, path.name)
    return cases


def load_conversations(path: Path = CONVERSATIONS_FILE) -> list[Conversation]:
    convos = [Conversation.model_validate(c) for c in _load_list(path, "conversations")]
    _unique_ids(convos, path.name)
    return convos


def load_system_prompt(path: Path = PROMPT_FILE) -> tuple[str, str]:
    """(version, prompt text). The first line is `version: N`; it is not sent to the model."""
    first, _, rest = path.read_text(encoding="utf-8").partition("\n")
    key, _, version = first.partition(":")
    if key.strip() != "version" or not version.strip():
        raise ValueError(f"{path.name} must start with a 'version: N' line")
    return version.strip(), rest.strip()
