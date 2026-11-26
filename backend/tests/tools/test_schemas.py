import json
import re

import pytest

from support.tools.schemas import (
    TOOL_DESCRIPTIONS,
    TOOL_SPECS,
    HandoffReason,
    as_langchain_tools,
)

SIX_TOOLS = {
    "get_order",
    "list_my_orders",
    "check_refund_eligibility",
    "request_refund",
    "create_handoff",
    "request_exchange",
}


def test_exactly_the_six_d7_tools() -> None:
    assert set(TOOL_SPECS) == SIX_TOOLS
    assert set(TOOL_DESCRIPTIONS) == SIX_TOOLS


def test_no_tool_takes_customer_id() -> None:
    for model in TOOL_SPECS.values():
        assert "customer_id" not in model.model_fields


def test_handoff_reasons_are_the_seven_codes_in_order() -> None:
    assert [r.value for r in HandoffReason] == [
        "angry",
        "two_failed",
        "damaged",
        "technical",
        "complaint",
        "cancellation",
        "human_requested",
    ]


@pytest.mark.parametrize("name", sorted(SIX_TOOLS))
def test_each_description_is_set_and_says_customer_is_known(name: str) -> None:
    description = TOOL_DESCRIPTIONS[name]
    assert description.strip()
    assert "session" in description


@pytest.mark.parametrize("name", sorted(SIX_TOOLS))
def test_arg_models_refuse_unknown_fields(name: str) -> None:
    assert TOOL_SPECS[name].model_config.get("extra") == "forbid"


@pytest.mark.parametrize("name", sorted(SIX_TOOLS))
def test_schema_sent_to_model_has_no_internal_notes(name: str) -> None:
    # Everything in the JSON schema reaches the model's prompt; decision IDs must not.
    schema = json.dumps(TOOL_SPECS[name].model_json_schema())
    assert not re.search(r"\bD\d+\b", schema)


def test_langchain_tools_match_specs_and_are_stubs() -> None:
    tools = {t.name: t for t in as_langchain_tools()}
    assert set(tools) == SIX_TOOLS
    for name, tool in tools.items():
        assert tool.args_schema is TOOL_SPECS[name]
        assert tool.description == TOOL_DESCRIPTIONS[name]
    with pytest.raises(NotImplementedError):
        tools["get_order"].invoke({"order_id": "ORD-1001"})
