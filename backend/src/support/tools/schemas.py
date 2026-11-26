"""Argument schemas and descriptions for the six D7 tools.

The customer always comes from the session, so no tool takes a customer_id (D3, D7).
Every argument model refuses unknown fields, so an LLM-invented argument is a malformed
call, never silently dropped. M1 uses these with stub bodies; M3 replaces the bodies
only, keeping the schemas and descriptions the model check measured.
"""

from enum import StrEnum
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict


class HandoffReason(StrEnum):
    # The fixed reason codes (D7 tightening 2; D14 adds human_requested). A comment, not a
    # docstring: Pydantic would send a docstring to the model as the field's description.
    ANGRY = "angry"
    TWO_FAILED = "two_failed"
    DAMAGED = "damaged"
    TECHNICAL = "technical"
    COMPLAINT = "complaint"
    CANCELLATION = "cancellation"
    HUMAN_REQUESTED = "human_requested"


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetOrderArgs(_Args):
    order_id: str


class ListMyOrdersArgs(_Args):
    pass


class CheckRefundEligibilityArgs(_Args):
    order_id: str
    item_ids: list[str]


class RequestRefundArgs(_Args):
    order_id: str
    item_ids: list[str]
    reason: str


class CreateHandoffArgs(_Args):
    reason: HandoffReason
    summary: str


class RequestExchangeArgs(_Args):
    order_id: str
    item_id: str
    new_size: str


TOOL_SPECS: dict[str, type[BaseModel]] = {
    "get_order": GetOrderArgs,
    "list_my_orders": ListMyOrdersArgs,
    "check_refund_eligibility": CheckRefundEligibilityArgs,
    "request_refund": RequestRefundArgs,
    "create_handoff": CreateHandoffArgs,
    "request_exchange": RequestExchangeArgs,
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    "get_order": (
        "Look up one order by its ID: shipment status, items, and any refund or exchange "
        "request with its approval state. The customer is already known from the session."
    ),
    "list_my_orders": (
        "List the customer's orders with their IDs, for when they don't give an order ID. "
        "The customer is already known from the session."
    ),
    "check_refund_eligibility": (
        "Check whether items of an order can be refunded under store policy, and the amount "
        "the store would refund; it moves no money. Use it before any refund request; the "
        "customer is already known from the session."
    ),
    "request_refund": (
        "Request a refund only after check_refund_eligibility said the items are eligible and "
        "the customer confirmed. It creates a request for human approval and moves no money "
        "yet; the customer is already known from the session."
    ),
    "create_handoff": (
        "Hand the conversation to a human with a reason code and a short summary of what the "
        "customer needs, e.g. when they are angry, ask for a person, report a damaged item or "
        "want to cancel. The customer is already known from the session."
    ),
    "request_exchange": (
        "Exchange one item of an order for another size; the store checks the exchange window, "
        "stock and the once-per-item rule. The customer is already known from the session."
    ),
}


def _not_in_m1(**_: Any) -> Any:
    # M1 never executes a tool: the check runner supplies canned results instead.
    raise NotImplementedError("Tool bodies arrive in M3; the M1 check uses canned results.")


def as_langchain_tools() -> list[StructuredTool]:
    """The six tools in the form bind_tools() takes, built from TOOL_SPECS."""
    return [
        StructuredTool.from_function(
            func=_not_in_m1,
            name=name,
            description=TOOL_DESCRIPTIONS[name],
            args_schema=spec,
        )
        for name, spec in TOOL_SPECS.items()
    ]
