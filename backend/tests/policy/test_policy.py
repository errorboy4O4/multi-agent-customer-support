"""The D2a policy rules as pure functions (M2 plan, Task 3).

No database and no model: every fact comes in as a dataclass, and `now` is always passed in.
"""

import random
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from support.domain import IST, Category, OrderStatus, PaymentMethod, RefundMethod
from support.policy import (
    ItemFacts,
    OrderFacts,
    Verdict,
    coupon_shares,
    damage_report_in_time,
    decide_exchange,
    decide_refund,
    refund_method_for,
    within_return_window,
)

DELIVERED = datetime(2026, 11, 28, 15, 0, tzinfo=IST)
NOW = datetime(2026, 12, 1, 12, 0, tzinfo=IST)  # STORE_NOW, 3 days after delivery


def _item(n: int, price: int, category: Category = Category.TSHIRT, **kw: object) -> ItemFacts:
    facts = ItemFacts(
        item_id=f"ITM-1-{n}",
        unit_price_paise=price,
        category=category,
        final_sale=False,
        custom_printed=False,
        size="M",
        refund_locked=False,
        exchanged=False,
    )
    return replace(facts, **kw)  # type: ignore[arg-type]


def _order(
    items: list[ItemFacts],
    *,
    status: OrderStatus = OrderStatus.DELIVERED,
    payment: PaymentMethod = PaymentMethod.UPI,
    coupon: int = 0,
    shipping: int = 0,
    delivered_at: datetime | None = DELIVERED,
) -> OrderFacts:
    if status not in (OrderStatus.DELIVERED, OrderStatus.RETURNED):
        delivered_at = None
    return OrderFacts(
        order_id="ORD-1",
        status=status,
        payment_method=payment,
        delivered_at=delivered_at,
        coupon_discount_paise=coupon,
        shipping_fee_paise=shipping,
        items=tuple(items),
    )


def _random_orders(n: int = 500) -> list[tuple[list[int], int]]:
    rng = random.Random(7)
    cases: list[tuple[list[int], int]] = []
    for _ in range(n):
        prices = [rng.randint(1, 500000) for _ in range(rng.randint(1, 6))]
        cases.append((prices, rng.randint(0, sum(prices))))
    return cases


# --- coupon split ---------------------------------------------------------------------


def test_coupon_shares_examples() -> None:
    assert coupon_shares([100000, 50000], 30000) == [20000, 10000]
    assert coupon_shares([33300, 33300, 33300], 10000) == [3334, 3333, 3333]
    assert coupon_shares([49900], 0) == [0]


def test_coupon_shares_rejects_bad_coupon() -> None:
    with pytest.raises(ValueError):
        coupon_shares([49900], -1)
    with pytest.raises(ValueError):
        coupon_shares([49900, 100], 50001)


def test_coupon_shares_always_sum_exactly() -> None:
    for prices, coupon in _random_orders():
        shares = coupon_shares(prices, coupon)
        assert sum(shares) == coupon, (prices, coupon)
        assert all(0 <= s <= p for s, p in zip(shares, prices, strict=True)), (prices, coupon)


def _sum_of_single_item_refunds(order: OrderFacts, item_order: list[str]) -> int:
    total = 0
    for item_id in item_order:
        decision = decide_refund(order, [item_id], NOW)
        assert decision.eligible, decision
        total += decision.amount_paise
    return total


def test_item_refunds_sum_to_amount_paid_for_items() -> None:
    order = _order([_item(n, 33300) for n in (1, 2, 3)], coupon=10000, shipping=9900)
    ids = [i.item_id for i in order.items]
    for item_order in (ids, list(reversed(ids)), [ids[1], ids[2], ids[0]]):
        assert _sum_of_single_item_refunds(order, item_order) == 99900 - 10000
    rng = random.Random(7)
    for prices, coupon in _random_orders():
        order = _order([_item(n, p) for n, p in enumerate(prices, 1)], coupon=coupon)
        ids = [i.item_id for i in order.items]
        rng.shuffle(ids)
        assert _sum_of_single_item_refunds(order, ids) == sum(prices) - coupon


# --- time rules -----------------------------------------------------------------------


def test_window_boundary_ist() -> None:
    delivered = datetime(2026, 11, 24, 22, 0, tzinfo=IST)
    assert within_return_window(delivered, datetime(2026, 12, 1, 23, 59, 59, tzinfo=IST))
    assert not within_return_window(delivered, datetime(2026, 12, 2, 0, 0, tzinfo=IST))


def test_window_uses_ist_calendar_days_for_utc_input() -> None:
    delivered = datetime(2026, 11, 24, 18, 30, tzinfo=UTC)  # 25 Nov 00:00 IST
    assert within_return_window(delivered, datetime(2026, 12, 2, 12, 0, tzinfo=IST))
    assert not within_return_window(delivered, datetime(2026, 12, 3, 0, 0, tzinfo=IST))


def test_naive_datetime_rejected() -> None:
    naive = datetime(2026, 11, 24, 22, 0)
    aware = datetime(2026, 11, 24, 22, 0, tzinfo=IST)
    for fn in (within_return_window, damage_report_in_time):
        with pytest.raises(ValueError):
            fn(naive, aware)
        with pytest.raises(ValueError):
            fn(aware, naive)
    order = _order([_item(1, 99900)])
    with pytest.raises(ValueError):
        decide_refund(order, ["ITM-1-1"], datetime(2026, 12, 1, 12, 0))


def test_damage_48h_boundary() -> None:
    delivered = datetime(2026, 11, 29, 10, 0, tzinfo=IST)
    assert damage_report_in_time(delivered, delivered + timedelta(hours=48))
    assert not damage_report_in_time(delivered, delivered + timedelta(hours=48, minutes=1))


# --- refunds --------------------------------------------------------------------------


def test_refund_method_for() -> None:
    assert refund_method_for(PaymentMethod.COD) is RefundMethod.STORE_CREDIT
    assert refund_method_for(PaymentMethod.UPI) is RefundMethod.ORIGINAL_PAYMENT
    assert refund_method_for(PaymentMethod.CARD) is RefundMethod.ORIGINAL_PAYMENT


def test_refund_delivered_prepaid_with_coupon() -> None:
    order = _order([_item(1, 100000), _item(2, 50000)], coupon=30000)
    decision = decide_refund(order, ["ITM-1-1"], NOW)
    assert decision.eligible
    assert decision.verdicts == {"ITM-1-1": Verdict.ELIGIBLE}
    assert decision.amount_paise == 80000
    assert decision.refund_method is RefundMethod.ORIGINAL_PAYMENT
    assert decision.includes_shipping is False


def test_refund_cod_is_store_credit() -> None:
    order = _order([_item(1, 100000), _item(2, 50000)], coupon=30000, payment=PaymentMethod.COD)
    decision = decide_refund(order, ["ITM-1-1"], NOW)
    assert decision.eligible
    assert decision.amount_paise == 80000
    assert decision.refund_method is RefundMethod.STORE_CREDIT


def test_refund_mixed_items_not_eligible() -> None:
    order = _order([_item(1, 99900), _item(2, 29900, Category.SOCKS)])
    decision = decide_refund(order, ["ITM-1-1", "ITM-1-2"], NOW)
    assert not decision.eligible
    assert decision.amount_paise == 0
    assert decision.refund_method is None
    assert decision.verdicts == {"ITM-1-1": Verdict.ELIGIBLE, "ITM-1-2": Verdict.NON_RETURNABLE}


def test_refund_order_level_verdicts() -> None:
    items = [_item(1, 100000), _item(2, 50000)]
    for status in (OrderStatus.PLACED, OrderStatus.SHIPPED, OrderStatus.OUT_FOR_DELIVERY):
        decision = decide_refund(_order(items, status=status), ["ITM-1-1"], NOW)
        assert decision.verdicts == {"ITM-1-1": Verdict.NOT_DELIVERED}, status
        assert not decision.eligible and decision.amount_paise == 0
    cancelled = decide_refund(_order(items, status=OrderStatus.CANCELLED), ["ITM-1-1"], NOW)
    assert cancelled.verdicts == {"ITM-1-1": Verdict.ORDER_CANCELLED}

    cod_rto = _order(items, status=OrderStatus.RTO, payment=PaymentMethod.COD, shipping=9900)
    decision = decide_refund(cod_rto, ["ITM-1-1", "ITM-1-2"], NOW)
    assert set(decision.verdicts.values()) == {Verdict.COD_RTO_NOTHING_TO_REFUND}
    assert not decision.eligible and decision.amount_paise == 0

    rto = _order(
        items, status=OrderStatus.RTO, payment=PaymentMethod.CARD, coupon=30000, shipping=9900
    )
    partial = decide_refund(rto, ["ITM-1-1"], NOW)
    assert partial.verdicts == {"ITM-1-1": Verdict.RTO_WHOLE_ORDER_ONLY}
    assert not partial.eligible and partial.amount_paise == 0

    whole = decide_refund(rto, ["ITM-1-2", "ITM-1-1"], NOW)
    assert whole.eligible
    assert whole.amount_paise == 100000 + 50000 - 30000 + 9900
    assert whole.refund_method is RefundMethod.ORIGINAL_PAYMENT
    assert whole.includes_shipping is True


def test_refund_item_verdicts() -> None:
    order = _order(
        [
            _item(1, 99900, refund_locked=True),
            _item(2, 99900, exchanged=True),
            _item(3, 99900, final_sale=True),
            _item(4, 99900, custom_printed=True),
            _item(5, 99900, Category.INNERWEAR),
        ]
    )
    expected = {
        "ITM-1-1": Verdict.ALREADY_REQUESTED,
        "ITM-1-2": Verdict.ALREADY_EXCHANGED,
        "ITM-1-3": Verdict.NON_RETURNABLE,
        "ITM-1-4": Verdict.NON_RETURNABLE,
        "ITM-1-5": Verdict.NON_RETURNABLE,
        "ITM-9-9": Verdict.NOT_IN_ORDER,
    }
    assert decide_refund(order, list(expected), NOW).verdicts == expected
    late = _order([_item(1, 99900)], delivered_at=NOW - timedelta(days=8))
    assert decide_refund(late, ["ITM-1-1"], NOW).verdicts == {"ITM-1-1": Verdict.WINDOW_EXPIRED}


def test_decide_refund_rejects_empty_and_duplicate_ids() -> None:
    order = _order([_item(1, 99900)])
    with pytest.raises(ValueError):
        decide_refund(order, [], NOW)
    with pytest.raises(ValueError):
        decide_refund(order, ["ITM-1-1", "ITM-1-1"], NOW)


# --- exchanges ------------------------------------------------------------------------


def test_exchange_verdicts() -> None:
    stock = {"S": 3, "M": 2, "L": 0}
    order = _order(
        [
            _item(1, 99900),
            _item(2, 99900, exchanged=True),
            _item(3, 99900, final_sale=True),
        ]
    )

    def verdict(o: OrderFacts, item_id: str, size: str) -> Verdict:
        return decide_exchange(o, item_id, size, stock, NOW)

    assert verdict(order, "ITM-1-1", "S") is Verdict.ELIGIBLE
    assert verdict(order, "ITM-1-1", "M") is Verdict.SAME_SIZE
    assert verdict(order, "ITM-1-1", "XXL") is Verdict.SIZE_UNAVAILABLE
    assert verdict(order, "ITM-1-1", "L") is Verdict.OUT_OF_STOCK
    assert verdict(order, "ITM-1-2", "S") is Verdict.ALREADY_EXCHANGED
    assert verdict(order, "ITM-1-3", "S") is Verdict.NON_RETURNABLE
    assert verdict(order, "ITM-9-9", "S") is Verdict.NOT_IN_ORDER
    late = _order([_item(1, 99900)], delivered_at=NOW - timedelta(days=8))
    assert verdict(late, "ITM-1-1", "S") is Verdict.WINDOW_EXPIRED
    shipped = _order([_item(1, 99900)], status=OrderStatus.SHIPPED)
    assert verdict(shipped, "ITM-1-1", "S") is Verdict.NOT_DELIVERED


# --- isolation ------------------------------------------------------------------------


def test_policy_imports_nothing_from_db_or_llm() -> None:
    # A fresh interpreter: this test process has already imported psycopg and langchain.
    code = (
        "import sys, support.policy\n"
        "bad = [m for m in ('psycopg', 'langchain_core', 'support.db') if m in sys.modules]\n"
        "print(','.join(bad))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""
