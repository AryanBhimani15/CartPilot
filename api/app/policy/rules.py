from __future__ import annotations

from dataclasses import dataclass

from app.policy.decisions import Allow, Deny, PolicyResult, RequireConfirmation

PAYMENT_TOOLS = frozenset({"create_razorpay_order", "place_order"})


@dataclass(frozen=True, slots=True)
class PolicyContext:
    """Facts collected by a tool adapter before deterministic rule evaluation.

    There is deliberately no model text here. The agent can propose an operation, but rules see
    only typed catalog, cart, inventory, and confirmation facts.
    """

    tool_name: str
    proposed_total_paise: int | None = None
    session_budget_paise: int | None = None
    merchant_max_cart_value_paise: int | None = None
    product_exists: bool = True
    requested_quantity: int | None = None
    available_quantity: int | None = None
    model_discount_paise: int | None = None
    computed_discount_paise: int | None = None
    price_snapshot_matches: bool = True
    confirmation_supplied: bool = False
    confirmation_valid: bool = False
    confirmation_cart_matches: bool = True
    substitution_requested: bool = False
    substitution_confirmed: bool = False


def payment_facts_present(context: PolicyContext) -> PolicyResult:
    """Deny a payment tool whose context omits the facts the money rules depend on.

    Every PolicyContext field defaults to a permissive value, so a tool adapter that forgets
    to populate one silently disables the rule that reads it. That is fail-open in the one
    place it must never be. Payment tools must state their total explicitly.
    """
    if context.tool_name not in PAYMENT_TOOLS:
        return Allow()
    if context.proposed_total_paise is None:
        return Deny(
            "REQUIRED_FACTS",
            "POLICY_FACTS_MISSING",
            "This payment could not be checked against the cart total.",
            "Recompute the cart total and retry the confirmed checkout.",
        )
    return Allow()


def budget_ceiling(context: PolicyContext) -> PolicyResult:
    if (
        context.session_budget_paise is not None
        and context.proposed_total_paise is not None
        and context.proposed_total_paise > context.session_budget_paise
    ):
        return Deny(
            "BUDGET_CEILING",
            "BUDGET_EXCEEDED",
            "That cart total exceeds the budget you stated.",
            "Offer an in-budget alternative or ask the user to revise their budget.",
        )
    return Allow()


def stock_available(context: PolicyContext) -> PolicyResult:
    if (
        context.requested_quantity is not None
        and context.available_quantity is not None
        and context.requested_quantity > context.available_quantity
    ):
        return Deny(
            "STOCK_AVAILABLE",
            "STOCK_UNAVAILABLE",
            "The requested quantity is no longer available.",
            "Choose an available variant or reduce the quantity.",
        )
    return Allow()


def no_phantom_sku(context: PolicyContext) -> PolicyResult:
    if not context.product_exists:
        return Deny(
            "NO_PHANTOM_SKU",
            "PRODUCT_NOT_FOUND",
            "That product or variant does not exist in the catalog.",
            "Search the catalog and use a returned product identifier.",
        )
    return Allow()


def discount_from_db(context: PolicyContext) -> PolicyResult:
    if context.model_discount_paise is not None:
        return Deny(
            "DISCOUNT_FROM_DB",
            "MODEL_DISCOUNT_REJECTED",
            "Discount amounts are calculated only from database offers.",
            "Apply a valid offer code and use the server-calculated total.",
        )
    return Allow()


def price_drift(context: PolicyContext) -> PolicyResult:
    if not context.price_snapshot_matches:
        return Deny(
            "PRICE_DRIFT",
            "PRICE_CHANGED",
            "A cart price changed after it was added.",
            "Show the updated total and ask the user to confirm it before checkout.",
        )
    return Allow()


def cart_fingerprint_matches(context: PolicyContext) -> PolicyResult:
    if context.confirmation_supplied and not context.confirmation_cart_matches:
        return Deny(
            "CART_FINGERPRINT",
            "CART_CHANGED",
            "The confirmation belongs to an earlier version of this cart.",
            "Review the current cart and confirm it again.",
        )
    return Allow()


def confirm_before_pay(context: PolicyContext) -> PolicyResult:
    if context.tool_name not in PAYMENT_TOOLS:
        return Allow()
    if not context.confirmation_supplied:
        return RequireConfirmation(
            "CONFIRM_BEFORE_PAY", "Please confirm the current cart before payment."
        )
    if not context.confirmation_valid:
        return Deny(
            "CONFIRM_BEFORE_PAY",
            "CONFIRMATION_INVALID",
            "The payment confirmation is invalid, expired, or already used.",
            "Review the cart and confirm it again.",
        )
    return Allow()


def no_silent_substitution(context: PolicyContext) -> PolicyResult:
    if context.substitution_requested and not context.substitution_confirmed:
        return Deny(
            "NO_SILENT_SUBSTITUTION",
            "SUBSTITUTION_NOT_CONFIRMED",
            "The requested item would be substituted without the user's approval.",
            "Ask the user to explicitly confirm the proposed substitution.",
        )
    return Allow()


def max_cart_value(context: PolicyContext) -> PolicyResult:
    if (
        context.merchant_max_cart_value_paise is not None
        and context.proposed_total_paise is not None
        and context.proposed_total_paise > context.merchant_max_cart_value_paise
    ):
        return Deny(
            "MAX_CART_VALUE",
            "MAX_CART_VALUE_EXCEEDED",
            "That cart exceeds the merchant's maximum allowed value.",
            "Reduce the cart total before checkout.",
        )
    return Allow()


RULES = (
    no_phantom_sku,
    stock_available,
    discount_from_db,
    budget_ceiling,
    max_cart_value,
    price_drift,
    no_silent_substitution,
    cart_fingerprint_matches,
    confirm_before_pay,
    # Last: a specific denial above is always the more useful answer. This only fires when
    # every other rule allowed, catching a payment whose context never stated a total.
    payment_facts_present,
)
