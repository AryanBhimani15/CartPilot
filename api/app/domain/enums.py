from __future__ import annotations

from enum import Enum


class OrderStatus(str, Enum):
    CREATED = "created"
    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class PaymentStatus(str, Enum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"
    REFUNDED = "refunded"


class SessionOutcome(str, Enum):
    ACTIVE = "active"
    CONVERTED = "converted"
    ABANDONED = "abandoned"
    FAILED = "failed"


class OfferType(str, Enum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_CONFIRMATION = "require_confirmation"


class EventType(str, Enum):
    SESSION_STARTED = "session_started"
    INTENT_CAPTURED = "intent_captured"
    PRODUCTS_SHOWN = "products_shown"
    PRODUCT_SELECTED = "product_selected"
    UPSELL_OFFERED = "upsell_offered"
    UPSELL_ACCEPTED = "upsell_accepted"
    CHECKOUT_STARTED = "checkout_started"
    PAYMENT_SUCCEEDED = "payment_succeeded"


class VariantAxis(str, Enum):
    FOOTWEAR_SIZE = "footwear_size"
    APPAREL_SIZE = "apparel_size"
    ONE_SIZE = "one_size"
