"""The D2a store policy as pure functions (M2 plan, Task 3).

Deterministic code decides eligibility and amount; the LLM only gathers facts and explains
(D2a, "Policy check"). Nothing here touches the database, a model or the clock: facts come
in as dataclasses and `now` is always an argument (M2 decision 5). Money is whole paise.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from support.domain import IST, Category, OrderStatus, PaymentMethod, RefundMethod

RETURN_WINDOW_DAYS = 7  # D2a: return / exchange window, 7 days from delivery
DAMAGE_REPORT_HOURS = 48  # D2a: damaged / wrong item, report within 48 h of delivery

# D2a: innerwear and socks are never returnable.
_NON_RETURNABLE_CATEGORIES = frozenset({Category.INNERWEAR, Category.SOCKS})
_NOT_YET_DELIVERED = frozenset(
    {OrderStatus.PLACED, OrderStatus.SHIPPED, OrderStatus.OUT_FOR_DELIVERY}
)


@dataclass(frozen=True)
class ItemFacts:
    item_id: str
    unit_price_paise: int
    category: Category
    final_sale: bool
    custom_printed: bool
    size: str
    refund_locked: bool  # in a refund request that wasn't rejected (D10 rule b)
    exchanged: bool


@dataclass(frozen=True)
class OrderFacts:
    order_id: str
    status: OrderStatus
    payment_method: PaymentMethod
    delivered_at: datetime | None
    coupon_discount_paise: int
    shipping_fee_paise: int
    items: tuple[ItemFacts, ...]


class Verdict(StrEnum):
    ELIGIBLE = "eligible"
    NOT_IN_ORDER = "not_in_order"
    NOT_DELIVERED = "not_delivered"
    WINDOW_EXPIRED = "window_expired"
    NON_RETURNABLE = "non_returnable"
    ALREADY_REQUESTED = "already_requested"
    ALREADY_EXCHANGED = "already_exchanged"
    ORDER_CANCELLED = "order_cancelled"
    COD_RTO_NOTHING_TO_REFUND = "cod_rto_nothing_to_refund"
    RTO_WHOLE_ORDER_ONLY = "rto_whole_order_only"
    SAME_SIZE = "same_size"
    SIZE_UNAVAILABLE = "size_unavailable"
    OUT_OF_STOCK = "out_of_stock"


@dataclass(frozen=True)
class RefundDecision:
    """All or nothing: `eligible` only if every requested item is, otherwise amount 0.

    The per-item verdicts let the agent explain and ask again with the eligible items.
    """

    eligible: bool
    verdicts: dict[str, Verdict]
    amount_paise: int
    refund_method: RefundMethod | None
    includes_shipping: bool


def _require_aware(*moments: datetime | None) -> None:
    for moment in moments:
        if moment is not None and moment.utcoffset() is None:
            raise ValueError("naive datetime: pass a timezone-aware datetime")


def is_non_returnable(item: ItemFacts) -> bool:
    # D2a: innerwear, socks, "final sale" and custom-printed items can't be returned.
    return item.category in _NON_RETURNABLE_CATEGORIES or item.final_sale or item.custom_printed


def coupon_shares(prices_paise: Sequence[int], coupon_paise: int) -> list[int]:
    """Split the coupon across items in proportion to price (D2a, "Partial refunds").

    Largest remainder: each item gets the floor of its exact share, and the paise left
    over go one each to the largest fractional parts, ties to the earlier item. The shares
    add up to exactly the coupon, and no share is more than its item's price.
    """
    if not prices_paise or any(p <= 0 for p in prices_paise):
        raise ValueError("prices must be a non-empty list of positive paise amounts")
    total = sum(prices_paise)
    if not 0 <= coupon_paise <= total:
        raise ValueError(f"coupon {coupon_paise} must be between 0 and the items' total {total}")
    shares = [coupon_paise * p // total for p in prices_paise]
    remainders = [coupon_paise * p % total for p in prices_paise]
    left_over = coupon_paise - sum(shares)
    by_remainder = sorted(range(len(shares)), key=lambda i: (-remainders[i], i))
    for i in by_remainder[:left_over]:
        shares[i] += 1
    return shares


def within_return_window(delivered_at: datetime, now: datetime) -> bool:
    # D2a: 7 days from delivery, counted as IST calendar days: a delivery on 24 Nov can be
    # returned until 1 Dec 23:59:59 IST, whatever offset the timestamps carry (decision 5).
    _require_aware(delivered_at, now)
    last_day = delivered_at.astimezone(IST).date() + timedelta(days=RETURN_WINDOW_DAYS)
    return now.astimezone(IST).date() <= last_day


def damage_report_in_time(delivered_at: datetime, now: datetime) -> bool:
    # D2a: damaged or wrong items are reported within exactly 48 hours of delivery.
    _require_aware(delivered_at, now)
    return now - delivered_at <= timedelta(hours=DAMAGE_REPORT_HOURS)


def refund_method_for(payment: PaymentMethod) -> RefundMethod:
    # D2a: prepaid goes back to the original method. COD is store credit only in v1 (D15).
    if payment is PaymentMethod.COD:
        return RefundMethod.STORE_CREDIT
    return RefundMethod.ORIGINAL_PAYMENT


def _check_ids(item_ids: Sequence[str]) -> None:
    if not item_ids:
        raise ValueError("item_ids is empty")
    if len(set(item_ids)) != len(item_ids):
        raise ValueError("item_ids repeats an item")


def _order_verdict(order: OrderFacts, item_ids: Sequence[str]) -> Verdict | None:
    """The order-level verdict for a refund, or None to go on to the item checks."""
    if order.status in _NOT_YET_DELIVERED:
        # D2a: after shipping, wait for delivery and return.
        return Verdict.NOT_DELIVERED
    if order.status is OrderStatus.CANCELLED:
        # D7: cancellation goes to a human, not through the agent.
        return Verdict.ORDER_CANCELLED
    if order.status is OrderStatus.RTO:
        if order.payment_method is PaymentMethod.COD:
            # D2a: a COD RTO is cancelled with nothing to refund.
            return Verdict.COD_RTO_NOTHING_TO_REFUND
        if set(item_ids) != {i.item_id for i in order.items}:
            # D2a: a prepaid RTO is a full refund of the whole order (M2 smaller choices).
            return Verdict.RTO_WHOLE_ORDER_ONLY
    return None


def _item_verdict(order: OrderFacts, item: ItemFacts, now: datetime) -> Verdict:
    if item.refund_locked:
        # D10 rule b: an item is locked by any refund request that wasn't rejected.
        return Verdict.ALREADY_REQUESTED
    if item.exchanged:
        # M2 smaller choices: an exchanged item can't be refunded or exchanged again.
        return Verdict.ALREADY_EXCHANGED
    if order.status is OrderStatus.RTO:
        # A prepaid RTO never reached the customer: the return rules don't apply (D2a).
        return Verdict.ELIGIBLE
    if is_non_returnable(item):
        return Verdict.NON_RETURNABLE
    if order.delivered_at is None:
        raise ValueError(f"{order.order_id} is {order.status} but has no delivered_at")
    if not within_return_window(order.delivered_at, now):
        return Verdict.WINDOW_EXPIRED
    return Verdict.ELIGIBLE


def decide_refund(order: OrderFacts, item_ids: Sequence[str], now: datetime) -> RefundDecision:
    _check_ids(item_ids)
    _require_aware(order.delivered_at, now)
    by_id = {item.item_id: item for item in order.items}
    order_level = _order_verdict(order, item_ids)
    verdicts: dict[str, Verdict] = {}
    for item_id in item_ids:
        item = by_id.get(item_id)
        if item is None:
            verdicts[item_id] = Verdict.NOT_IN_ORDER
        elif order_level is not None:
            verdicts[item_id] = order_level
        else:
            verdicts[item_id] = _item_verdict(order, item, now)

    if any(v is not Verdict.ELIGIBLE for v in verdicts.values()):
        # All or nothing (M2 smaller choices, approved knowingly 27 Nov 2026).
        return RefundDecision(False, verdicts, 0, None, False)

    # D2a: each item is refunded at its price minus its share of the coupon. The shares
    # are over the whole order, so separate requests add up to exactly what was paid.
    shares = coupon_shares([i.unit_price_paise for i in order.items], order.coupon_discount_paise)
    share_by_id = dict(zip(by_id, shares, strict=True))
    amount = sum(by_id[i].unit_price_paise - share_by_id[i] for i in item_ids)
    # D2a: shipping is refunded only on a prepaid RTO (the only RTO that gets this far).
    includes_shipping = order.status is OrderStatus.RTO
    if includes_shipping:
        amount += order.shipping_fee_paise
    return RefundDecision(
        True, verdicts, amount, refund_method_for(order.payment_method), includes_shipping
    )


def decide_exchange(
    order: OrderFacts,
    item_id: str,
    new_size: str,
    stock_by_size: Mapping[str, int],
    now: datetime,
) -> Verdict:
    """`stock_by_size` holds the item's product sizes; a size missing from it is unavailable."""
    _require_aware(order.delivered_at, now)
    item = next((i for i in order.items if i.item_id == item_id), None)
    if item is None:
        return Verdict.NOT_IN_ORDER
    if order.status is OrderStatus.CANCELLED:
        return Verdict.ORDER_CANCELLED
    if order.status not in (OrderStatus.DELIVERED, OrderStatus.RETURNED):
        # Only a delivered item can be exchanged; an RTO never reached the customer.
        return Verdict.NOT_DELIVERED
    verdict = _item_verdict(order, item, now)
    if verdict is not Verdict.ELIGIBLE:
        return verdict
    # D2a: a free size exchange, once per item, if the new size is in stock.
    if new_size == item.size:
        return Verdict.SAME_SIZE
    if new_size not in stock_by_size:
        return Verdict.SIZE_UNAVAILABLE
    if stock_by_size[new_size] <= 0:
        return Verdict.OUT_OF_STOCK
    return Verdict.ELIGIBLE
