"""Scores one model reply against one M1 check case, and applies the T1 rule (D3, D9).

Only tool calls are read, never `content`: Gemini returns content as a list of parts,
and the check grades the action, not the wording. Fail reasons are fixed codes so the
summary can count them. `error` is set by the runner (provider errors), never here.
"""

import json
from dataclasses import dataclass
from statistics import fmean
from typing import Annotated, Any, Literal, Self

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.messages.tool import tool_call
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from support.tools.schemas import TOOL_SPECS

Reason = Literal[
    "ok", "no_tool_call", "wrong_tool", "wrong_args", "malformed", "wrong_refund", "error"
]

REFUND_TOOL = "request_refund"
T1_RUNS = 3
T1_MIN_MEAN = 0.90
# Scores are k/20 fractions, so a float mean can land a hair under 0.90 (e.g. 0.8999...).
_FLOAT_SLACK = 1e-9


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HistoryToolCall(_Entry):
    name: str
    args: dict[str, Any]

    @model_validator(mode="after")
    def _valid_for_its_tool(self) -> Self:
        spec = TOOL_SPECS.get(self.name)
        if spec is None:
            raise ValueError(f"history calls {self.name!r}, which is not one of the D7 tools")
        try:
            spec.model_validate(self.args)
        except ValidationError as exc:
            raise ValueError(f"history call to {self.name} has invalid args: {exc}") from None
        return self


class UserEntry(_Entry):
    role: Literal["user"]
    content: str


class AssistantEntry(_Entry):
    role: Literal["assistant"]
    content: str = ""
    tool_calls: list[HistoryToolCall] = []


class ToolEntry(_Entry):
    role: Literal["tool"]
    name: str
    content: str | dict[str, Any]  # a dict is sent as JSON text


HistoryEntry = Annotated[UserEntry | AssistantEntry | ToolEntry, Field(discriminator="role")]


class CheckCase(BaseModel):
    """One case from cases.yaml. Unknown keys, tools or argument names are refused.

    History is a real earlier exchange (decided 26 Nov 2026, Task 6): every assistant
    tool call must be answered, in order, by the tool entries right after it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    lang: Literal["en", "hinglish"]
    history: list[HistoryEntry]
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

    @model_validator(mode="after")
    def _tool_entries_answer_calls(self) -> Self:
        waiting: list[str] = []  # tool names still owed a result, in call order
        for entry in self.history:
            if isinstance(entry, ToolEntry):
                if not waiting or waiting[0] != entry.name:
                    raise ValueError(f"tool entry {entry.name!r} answers no pending call")
                waiting.pop(0)
                continue
            if waiting:
                raise ValueError(f"history has unanswered tool calls: {waiting}")
            if isinstance(entry, AssistantEntry):
                waiting = [c.name for c in entry.tool_calls]
        if waiting:
            raise ValueError(f"history has unanswered tool calls: {waiting}")
        return self


def case_messages(case: CheckCase) -> list[BaseMessage]:
    """The case's history plus its message, as LangChain messages (no system prompt).

    Call IDs are generated here, so cases.yaml never has to keep them in step.
    """
    messages: list[BaseMessage] = []
    pending: list[str] = []
    for n, entry in enumerate(case.history):
        if isinstance(entry, UserEntry):
            messages.append(HumanMessage(entry.content))
        elif isinstance(entry, AssistantEntry):
            calls = [
                tool_call(name=c.name, args=c.args, id=f"hist-{n}-{i}")
                for i, c in enumerate(entry.tool_calls)
            ]
            pending = [c["id"] or "" for c in calls]
            messages.append(AIMessage(content=entry.content, tool_calls=calls))
        else:
            content = entry.content
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            messages.append(ToolMessage(text, tool_call_id=pending.pop(0), name=entry.name))
    messages.append(HumanMessage(case.message))
    return messages


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
