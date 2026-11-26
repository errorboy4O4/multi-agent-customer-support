"""Scores one model reply against one M1 check case, and applies the T1 rule (D3, D9).

Only tool calls are read, never `content`: Gemini returns content as a list of parts,
and the check grades the action, not the wording. Fail reasons are fixed codes so the
summary can count them. `error` is set by the runner (provider errors), never here.
"""

from dataclasses import dataclass
from statistics import fmean
from typing import Any, Literal, Self

from langchain_core.messages import AIMessage
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from support.tools.schemas import TOOL_SPECS

Reason = Literal[
    "ok", "no_tool_call", "wrong_tool", "wrong_args", "malformed", "wrong_refund", "error"
]

REFUND_TOOL = "request_refund"
T1_RUNS = 3
T1_MIN_MEAN = 0.90
# Scores are k/20 fractions, so a float mean can land a hair under 0.90 (e.g. 0.8999...).
_FLOAT_SLACK = 1e-9


class CheckCase(BaseModel):
    """One case from cases.yaml. Unknown keys, tools or argument names are refused."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    lang: Literal["en", "hinglish"]
    history: list[dict[str, Any]]
    message: str
    expected_tool: str
    expected_args: dict[str, Any]

    @model_validator(mode="after")
    def _known_tool_and_args(self) -> Self:
        spec = TOOL_SPECS.get(self.expected_tool)
        if spec is None:
            raise ValueError(f"expected_tool {self.expected_tool!r} is not one of the D7 tools")
        unknown = set(self.expected_args) - set(spec.model_fields)
        if unknown:
            raise ValueError(f"expected_args has names {self.expected_tool} lacks: {unknown}")
        return self


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    passed: bool
    reason: Reason
    called_tool: str | None
    wrong_refund: bool


def _matches(key: str, actual: Any, expected: Any) -> bool:
    if key == "item_ids":
        return set(actual) == set(expected)
    return actual == expected  # exact: no trimming or case folding (decided 26 Nov 2026)


def score_case(case: CheckCase, msg: AIMessage) -> CaseResult:
    calls = msg.tool_calls
    invalid = msg.invalid_tool_calls
    names = [c["name"] for c in calls] + [c.get("name") for c in invalid]
    first_name = calls[0]["name"] if calls else (invalid[0].get("name") if invalid else None)

    def fail(reason: Reason, wrong_refund: bool = False) -> CaseResult:
        return CaseResult(case.id, False, reason, first_name, wrong_refund)

    # A refund attempt anywhere in the reply, even a malformed one, outranks every other reason.
    if case.expected_tool != REFUND_TOOL and REFUND_TOOL in names:
        return fail("wrong_refund", wrong_refund=True)
    if invalid:
        return fail("malformed")
    if not calls:
        return fail("no_tool_call")
    first = calls[0]
    if first["name"] != case.expected_tool:
        return fail("wrong_tool")
    try:
        parsed = TOOL_SPECS[first["name"]].model_validate(first["args"])
    except ValidationError:
        return fail("malformed")
    for key, expected in case.expected_args.items():
        if not _matches(key, getattr(parsed, key), expected):
            return fail("wrong_args")
    return CaseResult(case.id, True, "ok", first_name, False)


def meets_t1(run_scores: list[float], wrong_refunds: int) -> bool:
    """T1: mean of the 3 run scores >= 0.90, and zero wrong refunds across them."""
    if len(run_scores) != T1_RUNS:
        raise ValueError(f"T1 needs exactly {T1_RUNS} runs, got {len(run_scores)}")
    return fmean(run_scores) >= T1_MIN_MEAN - _FLOAT_SLACK and wrong_refunds == 0
