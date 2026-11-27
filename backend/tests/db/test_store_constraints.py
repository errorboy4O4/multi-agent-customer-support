"""The store schema refuses bad rows by itself (D10, M2 plan Task 2).

Each test builds a few base rows, then inserts or updates inside a savepoint and expects
the database to refuse. The `conn` fixture rolls everything back afterwards.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg
import pytest
from psycopg import errors

from support.tools.schemas import HandoffReason

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 28, 10, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Base:
    alice: int
    bob: int
    tee: int
    hoodie: int
    tee_m: int
    tee_l: int
    hoodie_m: int


def _one(conn: psycopg.Connection, query: str, params: tuple[object, ...] = ()) -> int:
    row = conn.execute(query, params).fetchone()  # type: ignore[arg-type]
    assert row is not None
    return int(row[0])


def _customer(conn: psycopg.Connection, n: int) -> int:
    return _one(
        conn,
        "INSERT INTO store.customers (full_name, phone, email, address, created_at)"
        " VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (f"Test Person {n}", f"+91 5000{n} 0000{n}", f"p{n}@example.com", f"{n} Test Road", T0),
    )


def _product(conn: psycopg.Connection, name: str, category: str, price: int) -> int:
    return _one(
        conn,
        "INSERT INTO store.products (name, category, price_paise) VALUES (%s, %s, %s) RETURNING id",
        (name, category, price),
    )


def _variant(conn: psycopg.Connection, product_id: int, size: str, stock: int = 5) -> int:
    return _one(
        conn,
        "INSERT INTO store.product_variants (product_id, size, stock) VALUES (%s, %s, %s)"
        " RETURNING id",
        (product_id, size, stock),
    )


def _order(
    conn: psycopg.Connection,
    order_id: str,
    customer_id: int,
    items: list[tuple[str, int, int]],
    status: str = "delivered",
) -> None:
    delivered_at = T0 if status in ("delivered", "returned") else None
    conn.execute(
        "INSERT INTO store.orders (id, customer_id, status, payment_method, placed_at,"
        " delivered_at) VALUES (%s, %s, %s, 'upi', %s, %s)",
        (order_id, customer_id, status, T0, delivered_at),
    )
    for item_id, variant_id, price in items:
        conn.execute(
            "INSERT INTO store.order_items (id, order_id, variant_id, unit_price_paise)"
            " VALUES (%s, %s, %s, %s)",
            (item_id, order_id, variant_id, price),
        )


@pytest.fixture
def base(conn: psycopg.Connection) -> Base:
    alice, bob = _customer(conn, 1), _customer(conn, 2)
    tee = _product(conn, "Test Tee", "tshirt", 99900)
    hoodie = _product(conn, "Test Hoodie", "hoodie", 199900)
    tee_m, tee_l = _variant(conn, tee, "M"), _variant(conn, tee, "L")
    hoodie_m = _variant(conn, hoodie, "M")
    _order(
        conn, "ORD-9001", alice, [("ITM-9001-1", tee_m, 99900), ("ITM-9001-2", hoodie_m, 199900)]
    )
    _order(conn, "ORD-9002", bob, [("ITM-9002-1", tee_l, 99900)])
    return Base(alice, bob, tee, hoodie, tee_m, tee_l, hoodie_m)


def _request(
    conn: psycopg.Connection,
    order_id: str,
    customer_id: int,
    item_ids: list[str],
    *,
    item_order_id: str | None = None,
    amount: int = 50000,
) -> int:
    request_id = _one(
        conn,
        "INSERT INTO store.refund_requests (order_id, customer_id, amount_paise, refund_method,"
        " reason) VALUES (%s, %s, %s, 'original_payment', 'does not fit') RETURNING id",
        (order_id, customer_id, amount),
    )
    for item_id in item_ids:
        conn.execute(
            "INSERT INTO store.refund_request_items (refund_request_id, order_id, order_item_id)"
            " VALUES (%s, %s, %s)",
            (request_id, item_order_id or order_id, item_id),
        )
    return request_id


def _set_status(conn: psycopg.Connection, request_id: int, status: str) -> None:
    conn.execute(
        "UPDATE store.refund_requests SET status = %s, decided_at = %s WHERE id = %s",
        (status, T0, request_id),
    )


def _payout(
    conn: psycopg.Connection,
    request_id: int,
    *,
    amount: int = 50000,
    request_status: str = "approved",
) -> None:
    conn.execute(
        "INSERT INTO store.payouts (refund_request_id, request_status, amount_paise,"
        " refund_method) VALUES (%s, %s, %s, 'original_payment')",
        (request_id, request_status, amount),
    )


def test_customer_fields_unique(conn: psycopg.Connection) -> None:
    _customer(conn, 1)
    clashes = {
        "full_name": ("Test Person 1", "+91 59999 99999", "x@example.com", "9 Other Road"),
        "phone": ("Someone Else", "+91 50001 00001", "x@example.com", "9 Other Road"),
        "email": ("Someone Else", "+91 59999 99999", "p1@example.com", "9 Other Road"),
        "address": ("Someone Else", "+91 59999 99999", "x@example.com", "1 Test Road"),
    }
    for field, values in clashes.items():
        with pytest.raises(errors.UniqueViolation, match=field), conn.transaction():
            conn.execute(
                "INSERT INTO store.customers (full_name, phone, email, address, created_at)"
                " VALUES (%s, %s, %s, %s, %s)",
                (*values, T0),
            )


def test_refund_item_locked_by_pending_request(conn: psycopg.Connection, base: Base) -> None:
    _request(conn, "ORD-9001", base.alice, ["ITM-9001-1"])
    with pytest.raises(errors.UniqueViolation), conn.transaction():
        _request(conn, "ORD-9001", base.alice, ["ITM-9001-1"])


def test_refund_item_free_after_rejection(conn: psycopg.Connection, base: Base) -> None:
    first = _request(conn, "ORD-9001", base.alice, ["ITM-9001-1"])
    _set_status(conn, first, "rejected")
    _request(conn, "ORD-9001", base.alice, ["ITM-9001-1"])  # no error


def test_approved_request_still_locks_item(conn: psycopg.Connection, base: Base) -> None:
    first = _request(conn, "ORD-9001", base.alice, ["ITM-9001-1"])
    _set_status(conn, first, "approved")
    with pytest.raises(errors.UniqueViolation), conn.transaction():
        _request(conn, "ORD-9001", base.alice, ["ITM-9001-1"])


def test_unrejecting_conflicting_request_fails(conn: psycopg.Connection, base: Base) -> None:
    first = _request(conn, "ORD-9001", base.alice, ["ITM-9001-1"])
    _set_status(conn, first, "rejected")
    _request(conn, "ORD-9001", base.alice, ["ITM-9001-1"])
    with pytest.raises(errors.UniqueViolation), conn.transaction():
        _set_status(conn, first, "pending")


def test_refund_item_must_belong_to_request_order(conn: psycopg.Connection, base: Base) -> None:
    # Bob's item, claimed through Alice's order: the item isn't in that order.
    with pytest.raises(errors.ForeignKeyViolation), conn.transaction():
        _request(conn, "ORD-9001", base.alice, ["ITM-9002-1"])
    # The item row names Bob's order, but the request is for Alice's order.
    with pytest.raises(errors.ForeignKeyViolation), conn.transaction():
        _request(conn, "ORD-9001", base.alice, ["ITM-9002-1"], item_order_id="ORD-9002")


def test_refund_request_customer_must_own_order(conn: psycopg.Connection, base: Base) -> None:
    with pytest.raises(errors.ForeignKeyViolation), conn.transaction():
        _request(conn, "ORD-9002", base.alice, ["ITM-9002-1"])


def test_one_payout_per_refund_request(conn: psycopg.Connection, base: Base) -> None:
    request_id = _request(conn, "ORD-9001", base.alice, ["ITM-9001-1"])
    _set_status(conn, request_id, "approved")
    _payout(conn, request_id)
    with pytest.raises(errors.UniqueViolation), conn.transaction():
        _payout(conn, request_id)


def test_payout_requires_approved_request(conn: psycopg.Connection, base: Base) -> None:
    request_id = _request(conn, "ORD-9001", base.alice, ["ITM-9001-1"])
    # Claiming the request is approved when it is still pending: no such (id, status) row.
    with pytest.raises(errors.ForeignKeyViolation), conn.transaction():
        _payout(conn, request_id)
    # Copying its real status: only an approved request can be paid.
    with pytest.raises(errors.CheckViolation), conn.transaction():
        _payout(conn, request_id, request_status="pending")


def test_payout_amount_must_match_request(conn: psycopg.Connection, base: Base) -> None:
    request_id = _request(conn, "ORD-9001", base.alice, ["ITM-9001-1"], amount=50000)
    _set_status(conn, request_id, "approved")
    with pytest.raises(errors.ForeignKeyViolation), conn.transaction():
        _payout(conn, request_id, amount=60000)


def test_paid_request_cannot_be_rejected(conn: psycopg.Connection, base: Base) -> None:
    request_id = _request(conn, "ORD-9001", base.alice, ["ITM-9001-1"])
    _set_status(conn, request_id, "approved")
    _payout(conn, request_id)
    # ON UPDATE RESTRICT raises its own error class (SQLSTATE 23001), not a plain FK error.
    with pytest.raises(errors.RestrictViolation), conn.transaction():
        _set_status(conn, request_id, "rejected")


def _exchange(conn: psycopg.Connection, base: Base, product_id: int, new_variant_id: int) -> None:
    conn.execute(
        "INSERT INTO store.exchanges (order_id, order_item_id, customer_id, product_id,"
        " new_variant_id) VALUES ('ORD-9001', 'ITM-9001-1', %s, %s, %s)",
        (base.alice, product_id, new_variant_id),
    )


def test_one_exchange_per_item(conn: psycopg.Connection, base: Base) -> None:
    _exchange(conn, base, base.tee, base.tee_l)
    with pytest.raises(errors.UniqueViolation), conn.transaction():
        _exchange(conn, base, base.tee, base.tee_l)


def test_exchange_variant_must_be_same_product(conn: psycopg.Connection, base: Base) -> None:
    # The hoodie's M variant, claimed as a tee size.
    with pytest.raises(errors.ForeignKeyViolation), conn.transaction():
        _exchange(conn, base, base.tee, base.hoodie_m)


def test_checks_reject_bad_values(conn: psycopg.Connection, base: Base) -> None:
    bad = [
        ("UPDATE store.product_variants SET stock = -1 WHERE id = %s", (base.tee_m,)),
        ("UPDATE store.products SET price_paise = 0 WHERE id = %s", (base.tee,)),
        ("UPDATE store.orders SET status = 'lost' WHERE id = %s", ("ORD-9002",)),
        ("UPDATE store.orders SET delivered_at = NULL WHERE id = %s", ("ORD-9001",)),
    ]
    for query, params in bad:
        with pytest.raises(errors.CheckViolation), conn.transaction():
            conn.execute(query, params)  # type: ignore[arg-type]


def test_handoff_reason_codes(conn: psycopg.Connection, base: Base) -> None:
    for reason in HandoffReason:
        conn.execute(
            "INSERT INTO store.handoffs (customer_id, reason, summary) VALUES (%s, %s, 'x')",
            (base.alice, reason.value),
        )
    with pytest.raises(errors.CheckViolation), conn.transaction():
        conn.execute(
            "INSERT INTO store.handoffs (customer_id, reason, summary) VALUES (%s, 'other', 'x')",
            (base.alice,),
        )
