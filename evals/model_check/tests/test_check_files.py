from collections import Counter

from evals.model_check.check_files import load_cases, load_conversations, load_system_prompt
from evals.model_check.scoring import AssistantEntry, case_messages
from support.tools.schemas import TOOL_SPECS

MUST_NOT_REFUND = {"mn-01", "mn-02"}


def test_check_files_load() -> None:
    cases = load_cases()
    assert len(cases) == 20
    assert Counter(c.expected_tool for c in cases) == {
        "get_order": 4,
        "list_my_orders": 2,
        "check_refund_eligibility": 3 + 2,  # 3 eligibility + 2 must-not-refund
        "request_refund": 3,
        "request_exchange": 2,
        "create_handoff": 4,
    }
    assert sum(c.lang == "hinglish" for c in cases) == 4
    assert all(c.expected_tool in TOOL_SPECS for c in cases)
    assert len(load_conversations()) == 5


def test_must_not_refund_cases_expect_the_eligibility_check() -> None:
    by_id = {c.id: c for c in load_cases()}
    assert all(by_id[i].expected_tool == "check_refund_eligibility" for i in MUST_NOT_REFUND)


def test_handoff_cases_cover_the_four_planned_reasons() -> None:
    reasons = {
        c.expected_args["reason"] for c in load_cases() if c.expected_tool == "create_handoff"
    }
    assert reasons == {"angry", "human_requested", "damaged", "cancellation"}


def test_refund_cases_show_the_eligibility_check_already_ran() -> None:
    for case in load_cases():
        if case.expected_tool != "request_refund":
            continue
        calls = [
            call
            for entry in case.history
            if isinstance(entry, AssistantEntry)
            for call in entry.tool_calls
        ]
        assert [c.name for c in calls] == ["check_refund_eligibility"], case.id
        assert calls[0].args["order_id"] == case.expected_args["order_id"], case.id
        assert set(calls[0].args["item_ids"]) == set(case.expected_args["item_ids"]), case.id


def test_every_case_builds_messages() -> None:
    for case in load_cases():
        assert case_messages(case)[-1].content == case.message


def test_system_prompt_has_a_version() -> None:
    version, text = load_system_prompt()
    assert version == "1"
    assert "version:" not in text
    assert "request_refund" in text
