import json
from typing import Any

import pytest
from langchain_core.messages import ToolMessage

from evals.model_check.check_files import Conversation
from evals.model_check.run_check import build_run_record, run_cases, run_conversation
from evals.model_check.scoring import CheckCase
from evals.model_check.tests.fakes import Scripted, StatusError, ai, groq_tool_use_failed
from support.llm.config import LLMConfig

CFG = LLMConfig("groq", "test-model", 0.6, "medium")
ORDER = {"order_id": "ORD-1001"}
NO_SLEEP: dict[str, Any] = {"sleep": lambda _s: None}


def case(case_id: str = "go-01") -> CheckCase:
    return CheckCase(
        id=case_id,
        lang="en",
        history=[],
        message="Where is ORD-1001?",
        expected_tool="get_order",
        expected_args=ORDER,
    )


def convo(turns: list[str], canned: list[dict[str, Any]] | None = None) -> Conversation:
    return Conversation.model_validate(
        {"id": "cv-t", "lang": "en", "turns": turns, "canned": canned or []}
    )


GET_ORDER_CANNED = [{"tool": "get_order", "args_match": ORDER, "result": {"status": "shipped"}}]


# --- run_cases -----------------------------------------------------------------------


def test_rerun_on_rate_limit_then_pass() -> None:
    fake = Scripted(StatusError(429), ai(("get_order", ORDER)))
    run = run_cases(fake.model, CFG, [case()], run_index=1, system_prompt="p", **NO_SLEEP)
    outcome = run.cases[0]
    assert outcome.result.passed is True
    assert run.reruns == 1
    assert [r.error_class for r in outcome.records] == ["rate_limit", None]
    assert (run.errors, run.score, run.valid) == (0, 1.0, True)


def test_rerun_waits_before_retrying() -> None:
    waits: list[float] = []
    fake = Scripted(StatusError(503), ai(("get_order", ORDER)))
    run_cases(fake.model, CFG, [case()], 1, system_prompt="p", rerun_wait_s=7.0, sleep=waits.append)
    assert waits == [7.0]


def test_error_after_two_reruns_not_counted() -> None:
    fake = Scripted(StatusError(429), StatusError(429), StatusError(429), ai(("get_order", ORDER)))
    run = run_cases(fake.model, CFG, [case("a"), case("b")], 1, system_prompt="p", **NO_SLEEP)
    assert [o.result.reason for o in run.cases] == ["error", "ok"]
    assert len(run.cases[0].records) == 3  # 1 attempt + 2 reruns, each one a request
    assert run.errors == 1
    assert run.score == 1.0  # 1 passed of 1 valid: the error is not in N (D3)
    assert run.valid is True


def test_run_invalid_after_three_errors() -> None:
    fake = Scripted(*[StatusError(429)] * 9)
    run = run_cases(
        fake.model, CFG, [case(str(i)) for i in range(3)], 1, system_prompt="p", **NO_SLEEP
    )
    assert (run.errors, run.valid, run.score) == (3, False, None)


def test_unclassified_error_stops_the_run() -> None:
    fake = Scripted(ValueError("bug"))
    with pytest.raises(ValueError):
        run_cases(fake.model, CFG, [case()], 1, system_prompt="p", **NO_SLEEP)


def test_wrong_refunds_are_counted() -> None:
    refund = {"order_id": "ORD-1001", "item_ids": ["I-1"], "reason": "x"}
    fake = Scripted(ai(("request_refund", refund)))
    run = run_cases(fake.model, CFG, [case()], 1, system_prompt="p", **NO_SLEEP)
    assert run.wrong_refunds == 1


def test_system_prompt_goes_first() -> None:
    fake = Scripted(ai(("get_order", ORDER)))
    run_cases(fake.model, CFG, [case()], 1, system_prompt="You are support.", **NO_SLEEP)
    assert fake.seen[0][0].content == "You are support."


def test_min_interval_paces_requests() -> None:
    waits: list[float] = []
    fake = Scripted(ai(("get_order", ORDER)), ai(("get_order", ORDER)))
    run_cases(
        fake.model,
        CFG,
        [case("a"), case("b")],
        1,
        system_prompt="p",
        min_interval_s=4.0,
        sleep=waits.append,
    )
    assert waits == [4.0]  # between the two requests, not before the first


# --- run_conversation ------------------------------------------------------------------


def test_conversation_counts_requests_and_tokens() -> None:
    fake = Scripted(
        ai(("get_order", ORDER), usage=(100, 20)),
        ai(text="It has shipped.", usage=(150, 10)),
        ai(text="You're welcome.", usage=(170, 5)),
    )
    result = run_conversation(
        fake.model,
        CFG,
        convo(["Where is ORD-1001?", "Thanks!"], GET_ORDER_CANNED),
        system_prompt="p",
        **NO_SLEEP,
    )
    assert result.requests == 3
    assert (result.input_tokens, result.output_tokens) == (420, 35)
    assert (result.missing_usage, result.unmatched_calls, result.invalid_calls) == (0, 0, 0)
    assert result.hit_cap is False and result.error is False
    tool_msg = fake.seen[1][-1]
    assert isinstance(tool_msg, ToolMessage)
    assert json.loads(str(tool_msg.content)) == {"status": "shipped"}


def test_conversation_missing_usage_counted() -> None:
    fake = Scripted(ai(text="Hi", usage=None), ai(text="Ok", usage=(10, 2)))
    result = run_conversation(fake.model, CFG, convo(["a", "b"]), system_prompt="p", **NO_SLEEP)
    assert result.missing_usage == 1
    assert (result.input_tokens, result.output_tokens) == (10, 2)  # never guessed as 0


def test_conversation_stops_at_call_cap() -> None:
    fake = Scripted(*[ai(("get_order", ORDER)) for _ in range(10)])
    result = run_conversation(
        fake.model, CFG, convo(["a", "b"], GET_ORDER_CANNED), system_prompt="p", **NO_SLEEP
    )
    assert result.hit_cap is True
    assert result.requests == 6
    assert len(fake.outputs) == 4  # nothing more was sent after the cap


def test_unmatched_call_gets_not_found_and_is_counted() -> None:
    fake = Scripted(
        ai(("get_order", {"order_id": "ORD-9999"})), ai(text="Not found."), ai(text="Ok")
    )
    result = run_conversation(
        fake.model, CFG, convo(["a", "b"], GET_ORDER_CANNED), system_prompt="p", **NO_SLEEP
    )
    assert result.unmatched_calls == 1
    assert json.loads(str(fake.seen[1][-1].content)) == {"error": "not_found"}


def test_invalid_args_get_invalid_argument_and_are_counted() -> None:
    bad = {"order_id": "ORD-1001", "item_ids": "I-1"}
    fake = Scripted(ai(("check_refund_eligibility", bad)), ai(text="Sorry."), ai(text="Ok"))
    result = run_conversation(fake.model, CFG, convo(["a", "b"]), system_prompt="p", **NO_SLEEP)
    assert result.invalid_calls == 1
    assert json.loads(str(fake.seen[1][-1].content)) == {"error": "invalid_argument"}


def test_canned_item_ids_match_as_a_set() -> None:
    canned = [
        {
            "tool": "check_refund_eligibility",
            "args_match": {"order_id": "ORD-1", "item_ids": ["A", "B"]},
            "result": {"eligible": True},
        }
    ]
    call = {"order_id": "ORD-1", "item_ids": ["B", "A"]}
    fake = Scripted(ai(("check_refund_eligibility", call)), ai(text="ok"), ai(text="ok"))
    result = run_conversation(
        fake.model, CFG, convo(["a", "b"], canned), system_prompt="p", **NO_SLEEP
    )
    assert result.unmatched_calls == 0


def test_model_reply_goes_back_unchanged() -> None:
    # Gemini's reply carries a thought signature inside its content parts; it must be
    # sent back as the same message, never rebuilt from its text or tool calls.
    first = ai(text=[{"type": "text", "text": "Hi", "extras": {"signature": "sig"}}])
    fake = Scripted(first, ai(text="Ok"))
    run_conversation(fake.model, CFG, convo(["a", "b"]), system_prompt="p", **NO_SLEEP)
    assert fake.seen[1][2] is first


def test_conversation_error_after_reruns_stops_it() -> None:
    fake = Scripted(ai(text="Hi"), StatusError(429), StatusError(429), StatusError(429))
    result = run_conversation(fake.model, CFG, convo(["a", "b"]), system_prompt="p", **NO_SLEEP)
    assert result.error is True
    assert result.requests == 1
    assert result.error_calls == 3


# --- the result file -----------------------------------------------------------------


def test_run_record_holds_the_full_settings() -> None:
    fake = Scripted(ai(("get_order", ORDER)))
    run = run_cases(fake.model, CFG, [case()], 1, system_prompt="p", **NO_SLEEP)
    record = build_run_record(
        CFG,
        run,
        run_id="r1",
        started_at="2026-11-26T19:00:00Z",
        prompt_version="1",
        commit="abc123",
        dirty=False,
    )
    assert record["settings"] == {
        "provider": "groq",
        "model": "test-model",
        "temperature": 0.6,
        "effort": "medium",
        "prompt_version": "1",
    }
    assert (record["commit"], record["dirty"], record["valid"]) == ("abc123", False, True)
    assert record["cases"][0]["result"]["reason"] == "ok"
    json.dumps(record)  # the whole record is JSON-serialisable


# --- Groq's 400 tool_use_failed (decided 26 Nov 2026, Task 8) ------------------------


def test_tool_use_failed_case_is_malformed_without_rerun() -> None:
    fake = Scripted(groq_tool_use_failed('get_order {"order_id": ORD-1001'))
    run = run_cases(fake.model, CFG, [case()], 1, system_prompt="p", **NO_SLEEP)
    outcome = run.cases[0]
    assert (outcome.result.reason, outcome.result.called_tool) == ("malformed", "get_order")
    assert (run.reruns, run.errors, run.valid) == (0, 0, True)
    assert len(outcome.records) == 1


def test_tool_use_failed_mentioning_refund_is_wrong_refund() -> None:
    text = 'check_refund_eligibility ok then request_refund {"order_id": "ORD-1001", ...'
    fake = Scripted(groq_tool_use_failed(text))
    run = run_cases(fake.model, CFG, [case()], 1, system_prompt="p", **NO_SLEEP)
    assert (run.cases[0].result.reason, run.wrong_refunds) == ("wrong_refund", 1)


def test_tool_use_failed_plain_text_is_malformed() -> None:
    fake = Scripted(groq_tool_use_failed("Sure, what's your order number?"))
    run = run_cases(fake.model, CFG, [case()], 1, system_prompt="p", **NO_SLEEP)
    assert (run.cases[0].result.reason, run.cases[0].result.called_tool) == ("malformed", None)


def test_conversation_tool_use_failed_naming_a_tool_gets_invalid_argument() -> None:
    fake = Scripted(
        groq_tool_use_failed('get_order {"order_id": '),
        ai(text="Sorry, which order?"),
        ai(text="Ok"),
    )
    result = run_conversation(
        fake.model, CFG, convo(["Where is ORD-1001?", "Thanks"]), system_prompt="p", **NO_SLEEP
    )
    assert result.invalid_calls == 1
    assert result.requests == 3 and result.error_calls == 0
    assert result.missing_usage == 1  # Groq sends no usage with the 400
    sent = fake.seen[1]
    assert sent[-2].tool_calls[0]["name"] == "get_order"  # type: ignore[attr-defined]
    assert json.loads(str(sent[-1].content)) == {"error": "invalid_argument"}


def test_conversation_tool_use_failed_plain_text_becomes_the_reply() -> None:
    fake = Scripted(groq_tool_use_failed("Could you share your order number?"), ai(text="Ok"))
    result = run_conversation(
        fake.model, CFG, convo(["Hi", "ORD-1001"]), system_prompt="p", **NO_SLEEP
    )
    assert result.invalid_calls == 1
    sent = fake.seen[1]
    assert sent[-2].content == "Could you share your order number?"
    assert sent[-1].content == "ORD-1001"  # the next customer turn followed


def test_result_file_keeps_failed_generation_for_review() -> None:
    # A wrong_refund found by the tool-name heuristic must stay reviewable by a person.
    text = "I can't call request_refund for that amount."
    fake = Scripted(groq_tool_use_failed(text))
    run = run_cases(fake.model, CFG, [case()], 1, system_prompt="p", **NO_SLEEP)
    record = build_run_record(
        CFG,
        run,
        run_id="r1",
        started_at="2026-11-27T00:00:00Z",
        prompt_version="1",
        commit="abc",
        dirty=False,
    )
    saved = json.loads(json.dumps(record))
    assert saved["cases"][0]["result"]["reason"] == "wrong_refund"
    assert saved["cases"][0]["records"][0]["failed_generation"] == text
