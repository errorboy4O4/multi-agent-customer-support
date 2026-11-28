"""The Python enums and the SQL CHECK lists name the same values (M2 plan, Task 3).

Both directions: an enum value the CHECK lacks would fail only at insert time, and a CHECK
value the enum lacks would be a status the code can't represent.
"""

import re
from enum import StrEnum

import psycopg
import pytest

from support.domain import Category, OrderStatus, PaymentMethod, RefundMethod
from support.tools.schemas import HandoffReason

pytestmark = pytest.mark.db

CHECKS: dict[str, type[StrEnum]] = {
    "orders_status_check": OrderStatus,
    "orders_payment_method_check": PaymentMethod,
    "refund_requests_refund_method_check": RefundMethod,
    "products_category_check": Category,
    "handoffs_reason_check": HandoffReason,
}


def _check_values(conn: psycopg.Connection, name: str) -> set[str]:
    row = conn.execute(
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c"
        " JOIN pg_namespace n ON n.oid = c.connamespace"
        " WHERE n.nspname = 'store' AND c.conname = %s",
        (name,),
    ).fetchone()
    assert row is not None, f"no CHECK constraint named {name}"
    # Postgres shows IN (...) as = ANY (ARRAY['a'::text, 'b'::text]).
    return set(re.findall(r"'([^']*)'", row[0]))


def test_enums_match_check_constraints(conn: psycopg.Connection) -> None:
    for name, enum in CHECKS.items():
        assert _check_values(conn, name) == {e.value for e in enum}, name
