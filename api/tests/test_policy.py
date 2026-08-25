from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commerce.cart import add_to_cart, create_cart
from app.db.models import AgentStep, Cart, Product, ProductVariant, Session
from app.db.seed.catalog import MERCHANT_ID
from app.domain.enums import PolicyDecision, SessionOutcome
from app.policy.confirmation import (
    _now,
    mint_confirmation_token,
    validate_confirmation_token,
)
from app.policy.decisions import Deny, RequireConfirmation
from app.policy.engine import (
    PolicyAudit,
    evaluate_post_tool,
    evaluate_pre_tool,
    execute_if_allowed,
    persist_decision,
)
from app.policy.rules import PolicyContext


def deny(context: PolicyContext, rule_id: str) -> Deny:
    result = evaluate_pre_tool(context)
    assert isinstance(result, Deny)
    assert result.rule_id == rule_id
    return result


def test_budget_ceiling_denies_over_stated_budget() -> None:
    deny(
        PolicyContext("add_to_cart", proposed_total_paise=500_001, session_budget_paise=500_000),
        "BUDGET_CEILING",
    )


def test_stock_available_denies_unavailable_quantity() -> None:
    deny(
        PolicyContext("add_to_cart", requested_quantity=2, available_quantity=1), "STOCK_AVAILABLE"
    )


def test_no_phantom_sku_denies_unknown_product() -> None:
    deny(PolicyContext("add_to_cart", product_exists=False), "NO_PHANTOM_SKU")


def test_discount_from_db_denies_model_supplied_discount() -> None:
    result = deny(
        PolicyContext("apply_offer", model_discount_paise=99_999, computed_discount_paise=60_000),
        "DISCOUNT_FROM_DB",
    )
    assert result.code == "MODEL_DISCOUNT_REJECTED"


def test_price_drift_denies_until_the_user_reconfirms() -> None:
    deny(PolicyContext("place_order", price_snapshot_matches=False), "PRICE_DRIFT")


def test_cart_fingerprint_denies_confirmation_for_an_old_cart() -> None:
    deny(
        PolicyContext(
            "place_order",
            confirmation_supplied=True,
            confirmation_valid=False,
            confirmation_cart_matches=False,
        ),
        "CART_FINGERPRINT",
    )


def test_confirm_before_pay_denies_forged_or_expired_confirmation() -> None:
    deny(
        PolicyContext("place_order", confirmation_supplied=True, confirmation_valid=False),
        "CONFIRM_BEFORE_PAY",
    )


def test_no_silent_substitution_denies_until_confirmed() -> None:
    deny(PolicyContext("add_to_cart", substitution_requested=True), "NO_SILENT_SUBSTITUTION")


def test_missing_payment_confirmation_returns_explicit_confirmation_state() -> None:
    result = evaluate_pre_tool(PolicyContext("place_order"))
    assert isinstance(result, RequireConfirmation)
    assert result.rule_id == "CONFIRM_BEFORE_PAY"


@pytest.mark.asyncio
async def test_invalid_place_order_token_cannot_reach_payment_action() -> None:
    payment_started = False

    async def payment_action() -> str:
        nonlocal payment_started
        payment_started = True
        return "would call Razorpay"

    decision, value = await execute_if_allowed(
        PolicyContext("place_order", confirmation_supplied=True, confirmation_valid=False),
        payment_action,
    )
    assert isinstance(decision, Deny)
    assert decision.rule_id == "CONFIRM_BEFORE_PAY"
    assert value is None
    assert not payment_started


def test_max_cart_value_denies_merchant_limit_breach() -> None:
    deny(
        PolicyContext(
            "add_to_cart", proposed_total_paise=2_000_001, merchant_max_cart_value_paise=2_000_000
        ),
        "MAX_CART_VALUE",
    )


async def _cart_with_item(session: AsyncSession) -> tuple[Cart, Session]:
    commerce_session = Session(
        merchant_id=MERCHANT_ID,
        outcome=SessionOutcome.ACTIVE,
        is_demo=True,
    )
    session.add(commerce_session)
    await session.flush()
    cart = await create_cart(session, commerce_session.id, MERCHANT_ID)
    row = (
        (
            await session.execute(
                select(Product, ProductVariant)
                .join(ProductVariant, ProductVariant.product_id == Product.id)
                .where(ProductVariant.stock_qty > 0)
                .order_by(Product.sku, ProductVariant.size)
            )
        )
        .tuples()
        .first()
    )
    assert row is not None
    _, variant = row
    await add_to_cart(session, cart.id, variant.id, 1)
    return cart, commerce_session


@pytest.mark.asyncio
async def test_forged_expired_and_cart_mismatched_tokens_cannot_authorise_payment(
    seeded_catalog: AsyncSession,
) -> None:
    cart, _ = await _cart_with_item(seeded_catalog)
    secret = "policy-test-secret"
    minted = await mint_confirmation_token(
        seeded_catalog, cart=cart, action="place_order", secret=secret
    )

    forged = await validate_confirmation_token(
        seeded_catalog,
        cart=cart,
        action="place_order",
        token=minted.token + "tampered",
        secret=secret,
    )
    assert not forged.valid
    deny(
        PolicyContext(
            "place_order",
            confirmation_supplied=forged.supplied,
            confirmation_valid=forged.valid,
            confirmation_cart_matches=forged.cart_matches,
        ),
        "CONFIRM_BEFORE_PAY",
    )

    expired = await validate_confirmation_token(
        seeded_catalog,
        cart=cart,
        action="place_order",
        token=minted.token,
        secret=secret,
        now=_now() + timedelta(minutes=6),
    )
    assert not expired.valid

    cart.total_paise += 1
    await seeded_catalog.flush()
    mismatched = await validate_confirmation_token(
        seeded_catalog, cart=cart, action="place_order", token=minted.token, secret=secret
    )
    assert not mismatched.valid and not mismatched.cart_matches
    deny(
        PolicyContext(
            "place_order",
            confirmation_supplied=mismatched.supplied,
            confirmation_valid=mismatched.valid,
            confirmation_cart_matches=mismatched.cart_matches,
        ),
        "CART_FINGERPRINT",
    )


@pytest.mark.asyncio
async def test_policy_decisions_are_persisted_and_post_checks_reapply_rules(
    seeded_catalog: AsyncSession,
) -> None:
    _, commerce_session = await _cart_with_item(seeded_catalog)
    decision = evaluate_post_tool(
        PolicyContext("add_to_cart", proposed_total_paise=500_001, session_budget_paise=500_000)
    )
    assert isinstance(decision, Deny)
    await persist_decision(
        seeded_catalog,
        PolicyAudit(
            session_id=commerce_session.id,
            step_no=1,
            tool_name="add_to_cart",
            args={"quantity": 1},
            result={"ok": False},
        ),
        decision,
    )
    recorded = await seeded_catalog.scalar(
        select(AgentStep).where(AgentStep.session_id == commerce_session.id, AgentStep.step_no == 1)
    )
    assert recorded is not None
    assert recorded.policy_decision == PolicyDecision.DENY
    assert recorded.policy_rule_id == "BUDGET_CEILING"
