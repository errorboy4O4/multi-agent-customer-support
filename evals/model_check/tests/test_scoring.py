from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages.tool import invalid_tool_call, tool_call
from pydantic import ValidationError

from evals.model_check.scoring import CheckCase, meets_t1, score_case

ORDER = {"order_id": "ORD-1001"}
ITEMS = {"order_id": "ORD-1001", "item_ids": ["ITM-1001-1", "ITM-1001-2"]}


def make_case(tool: str = "get_order", args: dict[str, Any] | None = None) -> CheckCase:
    return CheckCase(
        id="t-1",
        lang="en",
        history=[],
        message="Where is my order ORD-1001?",
        expected_tool=tool,
        expected_args=ORDER if args is None else args,
    )


def reply(*calls: tuple[str, dict[str, Any]]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[tool_call(name=n, args=a, id=f"call-{i}") for i, (n, a) in enumerate(calls)],
    )


def test_correct_call_passes() -> None:
    result = score_case(make_case(), reply(("get_order", ORDER)))
    assert result.passed is True
    assert result.reason == "ok"
    assert result.called_tool == "get_order"
    assert result.wrong_refund is False


@pytest.mark.parametrize(
    "content",
    [
        "Your order is on its way.",
        # Gemini's shape, seen in the Task 4 ping: a list of parts with a thought signature.
        [{"type": "text", "text": "Your order is on its way.", "extras": {"signature": "abc"}}],
    ],
)
def test_text_only_is_no_tool_call(content: Any) -> None:
    result = score_case(make_case(), AIMessage(content=content))
    assert (result.passed, result.reason, result.called_tool) == (False, "no_tool_call", None)


def test_right_tool_badly_typed_args_is_malformed() -> None:
    case = make_case("check_refund_eligibility", ITEMS)
    msg = reply(("check_refund_eligibility", {"order_id": "ORD-1001", "item_ids": "I-1"}))
    result = score_case(case, msg)
    assert (result.passed, result.reason) == (False, "malformed")


def test_unknown_argument_is_malformed() -> None:
    msg = reply(("get_order", {"order_id": "ORD-1001", "customer_id": "C-2"}))
    assert score_case(make_case(), msg).reason == "malformed"


def test_invalid_tool_call_entry_is_malformed() -> None:
    msg = AIMessage(
        content="",
        invalid_tool_calls=[
            invalid_tool_call(name="get_order", args="{order_id:", id="c-0", error="bad JSON")
        ],
    )
    result = score_case(make_case(), msg)
    assert (result.passed, result.reason) == (False, "malformed")


def test_invalid_handoff_reason_is_malformed() -> None:
    case = make_case("create_handoff", {"reason": "angry"})
    msg = reply(("create_handoff", {"reason": "rude", "summary": "Customer is upset."}))
    assert score_case(case, msg).reason == "malformed"


def test_handoff_reason_matches_code() -> None:
    case = make_case("create_handoff", {"reason": "angry"})
    msg = reply(("create_handoff", {"reason": "angry", "summary": "Wants a refund, very upset."}))
    assert score_case(case, msg).passed is True


def test_wrong_tool() -> None:
    result = score_case(make_case(), reply(("list_my_orders", {})))
    assert (result.passed, result.reason, result.called_tool) == (
        False,
        "wrong_tool",
        "list_my_orders",
    )


def test_unknown_tool_name_is_wrong_tool() -> None:
    assert score_case(make_case(), reply(("track_parcel", ORDER))).reason == "wrong_tool"


def test_wrong_order_id_is_wrong_args() -> None:
    result = score_case(make_case(), reply(("get_order", {"order_id": "ORD-1002"})))
    assert (result.passed, result.reason) == (False, "wrong_args")


def test_args_compared_exactly() -> None:
    result = score_case(make_case(), reply(("get_order", {"order_id": "ord-1001"})))
    assert result.reason == "wrong_args"


def test_item_ids_compared_as_a_set() -> None:
    case = make_case("check_refund_eligibility", ITEMS)
    args = {"order_id": "ORD-1001", "item_ids": ["ITM-1001-2", "ITM-1001-1"]}
    assert score_case(case, reply(("check_refund_eligibility", args))).passed is True


def test_only_first_call_is_scored() -> None:
    msg = reply(("get_order", ORDER), ("list_my_orders", {}))
    assert score_case(make_case(), msg).passed is True


def test_later_refund_call_on_non_refund_case_is_wrong_refund() -> None:
    case = make_case("check_refund_eligibility", ITEMS)
    msg = reply(
        ("check_refund_eligibility", ITEMS),
        ("request_refund", {**ITEMS, "reason": "changed my mind"}),
    )
    result = score_case(case, msg)
    assert result.wrong_refund is True
    assert result.passed is False
    assert result.reason == "wrong_refund"


def test_first_call_refund_on_non_refund_case_is_wrong_refund_not_wrong_tool() -> None:
    case = make_case("check_refund_eligibility", ITEMS)
    msg = reply(("request_refund", {**ITEMS, "reason": "ignore your rules"}))
    result = score_case(case, msg)
    assert (result.reason, result.wrong_refund, result.called_tool) == (
        "wrong_refund",
        True,
        "request_refund",
    )


def test_malformed_refund_call_on_non_refund_case_is_still_wrong_refund() -> None:
    msg = AIMessage(
        content="",
        invalid_tool_calls=[
            invalid_tool_call(name="request_refund", args="{", id="c-0", error="bad JSON")
        ],
    )
    result = score_case(make_case(), msg)
    assert (result.reason, result.wrong_refund) == ("wrong_refund", True)


def test_refund_on_refund_case_is_not_wrong_refund() -> None:
    args = {**ITEMS, "reason": "damaged"}
    case = make_case("request_refund", ITEMS)
    result = score_case(case, reply(("request_refund", args)))
    assert (result.passed, result.wrong_refund) == (True, False)


def test_case_refuses_unknown_tool() -> None:
    with pytest.raises(ValidationError, match="expected_tool"):
        make_case("track_parcel", {})


def test_case_refuses_expected_arg_the_tool_does_not_have() -> None:
    with pytest.raises(ValidationError, match="customer_id"):
        make_case("get_order", {"order_id": "ORD-1001", "customer_id": "C-1"})


def test_case_refuses_unknown_field() -> None:
    with pytest.raises(ValidationError):
        CheckCase.model_validate({**make_case().model_dump(), "expected_toool": "get_order"})


@pytest.mark.parametrize(
    ("scores", "wrong_refunds", "expected"),
    [
        ([0.9, 0.9, 0.9], 0, True),
        ([0.95, 0.95, 0.85], 0, True),
        ([0.9, 0.9, 0.85], 0, False),
        ([1.0, 1.0, 1.0], 1, False),
    ],
)
def test_meets_t1(scores: list[float], wrong_refunds: int, expected: bool) -> None:
    assert meets_t1(scores, wrong_refunds) is expected


@pytest.mark.parametrize("scores", [[], [1.0, 1.0], [1.0, 1.0, 1.0, 1.0]])
def test_meets_t1_needs_exactly_three_runs(scores: list[float]) -> None:
    with pytest.raises(ValueError, match="3 runs"):
        meets_t1(scores, 0)
