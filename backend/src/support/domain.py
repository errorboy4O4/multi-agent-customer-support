"""Store vocabulary shared by the policy, the seed and (from M3) the tools.

Each enum's values match a CHECK list in migrations/001_store.sql exactly; the db test
test_enums_match_check_constraints fails if the two drift apart.
"""

from datetime import timedelta, timezone
from enum import StrEnum

# India has one fixed offset and no daylight saving, so no tzdata is needed (M2 decision 5).
IST = timezone(timedelta(hours=5, minutes=30), "IST")


class OrderStatus(StrEnum):
    PLACED = "placed"
    SHIPPED = "shipped"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    RTO = "rto"
    CANCELLED = "cancelled"
    RETURNED = "returned"


class PaymentMethod(StrEnum):
    COD = "cod"
    UPI = "upi"
    CARD = "card"


class RefundMethod(StrEnum):
    ORIGINAL_PAYMENT = "original_payment"
    STORE_CREDIT = "store_credit"


class Category(StrEnum):
    TSHIRT = "tshirt"
    SHIRT = "shirt"
    HOODIE = "hoodie"
    JOGGERS = "joggers"
    JEANS = "jeans"
    KURTA = "kurta"
    DRESS = "dress"
    SHORTS = "shorts"
    INNERWEAR = "innerwear"
    SOCKS = "socks"
