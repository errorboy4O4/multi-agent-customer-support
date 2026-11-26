import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import ValidationError

from evals.model_check.scoring import CheckCase, case_messages

CHECK = {"order_id": "ORD-1015", "item_ids": ["ITM-1015-1"]}
REFUND_HISTORY: list[dict[str, Any]] = [
    {"role": "user", "content": "I want to return ITM-1015-1 from ORD-1015."},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"name": "check_refund_eligibility", "args": CHECK}],
    },
    {
        "role": "tool",
        "name": "check_refund_eligibility",
        "content": {"eligible": True, "amount_inr": 899},
    },
    {"role": "assistant", "content": "It's eligible for ₹899. Shall I submit it for approval?"},
]


def make_case(history: list[dict[str, Any]]) -> CheckCase:
    return CheckCase.model_validate(
        {
            "id": "rr-test",
            "lang": "en",
            "history": history,
            "message": "Yes, go ahead.",
            "expected_tool": "request_refund",
            "expected_args": CHECK,
        }
    )


def test_case_messages_rebuilds_the_tool_exchange() -> None:
    msgs = case_messages(make_case(REFUND_HISTORY))
    assert [type(m) for m in msgs] == [
        HumanMessage,
        AIMessage,
        ToolMessage,
        AIMessage,
        HumanMessage,
    ]
    call_msg, tool_msg = msgs[1], msgs[2]
    assert isinstance(call_msg, AIMessage) and isinstance(tool_msg, ToolMessage)
    assert call_msg.tool_calls[0]["name"] == "check_refund_eligibility"
    assert call_msg.tool_calls[0]["args"] == CHECK
    assert tool_msg.tool_call_id == call_msg.tool_calls[0]["id"]
    assert json.loads(str(tool_msg.content)) == {"eligible": True, "amount_inr": 899}
    assert msgs[-1].content == "Yes, go ahead."


def test_tool_result_keeps_rupee_sign_readable() -> None:
    history = [*REFUND_HISTORY[:2], {**REFUND_HISTORY[2], "content": {"note": "₹899"}}]
    tool_msg = case_messages(make_case(history))[2]
    assert "₹899" in str(tool_msg.content)


def test_empty_history_gives_just_the_message() -> None:
    msgs = case_messages(make_case([]))
    assert len(msgs) == 1 and isinstance(msgs[0], HumanMessage)


@pytest.mark.parametrize(
    ("history", "match"),
    [
        ([{"role": "customer", "content": "hi"}], "role"),
        ([{"role": "user", "content": "hi", "extra": 1}], "extra"),
        (
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"name": "track_parcel", "args": {}}],
                }
            ],
            "track_parcel",
        ),
        (
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"name": "get_order", "args": {"order_id": 1015}}],
                },
                {"role": "tool", "name": "get_order", "content": "{}"},
            ],
            "get_order",
        ),
        ([{"role": "tool", "name": "get_order", "content": "{}"}], "answers no"),
        ([REFUND_HISTORY[1], {"role": "tool", "name": "get_order", "content": "{}"}], "answers no"),
        ([REFUND_HISTORY[1], REFUND_HISTORY[3]], "unanswered"),
        (REFUND_HISTORY[:2], "unanswered"),
    ],
    ids=[
        "unknown-role",
        "unknown-key",
        "unknown-tool",
        "bad-args",
        "tool-without-call",
        "tool-answers-other-name",
        "call-not-answered-before-next-turn",
        "call-not-answered-at-end",
    ],
)
def test_history_mistakes_fail_at_load(history: list[dict[str, Any]], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        make_case(history)
