from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commerce.cart import add_to_cart, create_cart
from app.db.models import (
    AgentStep,
    Cart,
    ConfirmationToken,
    Merchant,
    Product,
    ProductVariant,
    Session,
)
from app.db.seed.catalog import MERCHANT_ID
from app.db.session import get_session_factory
from app.domain.enums import PolicyDecision, SessionOutcome, VariantAxis
from app.policy.confirmation import (
    _now,
    consume_confirmation_token,
    mint_confirmation_token,
    validate_confirmation_token,
)
from app.policy.decisions import Allow, Deny, RequireConfirmation
from app.policy.engine import (
    PolicyAudit,
    evaluate_post_tool,
    evaluate_pre_tool,
    execute_if_allowed,
    persist_decision,
)
from app.policy.rules import PolicyContext

SECRET = "policy-test-secret"


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


@pytest.mark.asyncio
async def test_confirmation_token_is_single_use(seeded_catalog: AsyncSession) -> None:
    """D-008 requires single use. Validation alone does not deliver it."""
    cart, _ = await _cart_with_item(seeded_catalog)
    minted = await mint_confirmation_token(
        seeded_catalog, cart=cart, action="place_order", secret=SECRET
    )

    first = await consume_confirmation_token(seeded_catalog, token=minted.token)
    second = await consume_confirmation_token(seeded_catalog, token=minted.token)
    assert first is True
    assert second is False, "a consumed confirmation token was accepted a second time"


@pytest.mark.asyncio
async def test_valid_token_cannot_be_replayed_through_the_execution_gate(
    seeded_catalog: AsyncSession,
) -> None:
    """The gate must consume the token itself.

    If consumption is left to downstream payment code, a single confirmation authorises an
    unbounded number of payment executions -- the exact property D-008 exists to prevent.
    """
    cart, _ = await _cart_with_item(seeded_catalog)
    minted = await mint_confirmation_token(
        seeded_catalog, cart=cart, action="place_order", secret=SECRET
    )
    validation = await validate_confirmation_token(
        seeded_catalog, cart=cart, action="place_order", token=minted.token, secret=SECRET
    )
    assert validation.valid

    context = PolicyContext(
        "place_order",
        proposed_total_paise=cart.total_paise,
        confirmation_supplied=True,
        confirmation_valid=True,
        confirmation_cart_matches=True,
    )
    executions: list[int] = []

    async def charge() -> int:
        executions.append(1)
        return len(executions)

    first_decision, _ = await execute_if_allowed(
        context, charge, session=seeded_catalog, confirmation_token=minted.token
    )
    second_decision, _ = await execute_if_allowed(
        context, charge, session=seeded_catalog, confirmation_token=minted.token
    )

    assert isinstance(first_decision, Allow)
    assert isinstance(second_decision, Deny)
    assert second_decision.rule_id == "CONFIRM_BEFORE_PAY"
    assert len(executions) == 1, "one confirmation authorised more than one payment execution"


def test_payment_tool_without_a_stated_total_is_denied_not_allowed() -> None:
    """Every PolicyContext field defaults permissively, which is fail-open for money tools."""
    result = evaluate_pre_tool(
        PolicyContext(
            "create_razorpay_order",
            confirmation_supplied=True,
            confirmation_valid=True,
        )
    )
    assert isinstance(result, Deny)
    assert result.rule_id == "REQUIRED_FACTS"


@pytest.mark.asyncio
async def test_concurrent_requests_cannot_both_consume_one_token() -> None:
    """Two in-flight place_order requests sharing a token must not both authorise payment."""
    merchant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    product_id = uuid.uuid4()
    variant_id = uuid.uuid4()
    session_factory = get_session_factory()
    token = ""

    async with session_factory() as setup:
        async with setup.begin():
            setup.add(Merchant(id=merchant_id, name=f"Token Merchant {merchant_id}"))
            setup.add(
                Session(id=session_id, merchant_id=merchant_id, outcome=SessionOutcome.ACTIVE)
            )
            setup.add(
                Product(
                    id=product_id,
                    merchant_id=merchant_id,
                    sku=f"TOKEN-{product_id}",
                    title="Token Runner",
                    brand="Test Brand",
                    category="running_shoes",
                    subcategory="test",
                    price_paise=100_000,
                    description="Test product",
                    attrs={"use_case": "daily_easy_runs", "gender": "unisex"},
                )
            )
            setup.add(
                ProductVariant(
                    id=variant_id,
                    product_id=product_id,
                    sku=f"TOKEN-VARIANT-{variant_id}",
                    axis=VariantAxis.FOOTWEAR_SIZE,
                    size="UK 9",
                    colour="Black",
                    stock_qty=5,
                    reserved_qty=0,
                )
            )
            await setup.flush()
            cart = await create_cart(setup, session_id, merchant_id)
            await add_to_cart(setup, cart.id, variant_id, 1)
            minted = await mint_confirmation_token(
                setup, cart=cart, action="place_order", secret=SECRET
            )
            token = minted.token

    # Both requests must finish validating BEFORE either consumes. Otherwise the second task
    # simply runs after the first has committed, never contends for the lock, and the test
    # proves nothing about concurrent consumption.
    validated = asyncio.Barrier(2)

    async def consume() -> bool:
        async with session_factory() as request_session:
            async with request_session.begin():
                request_cart = await request_session.scalar(
                    select(Cart).where(Cart.session_id == session_id)
                )
                assert request_cart is not None
                await validate_confirmation_token(
                    request_session,
                    cart=request_cart,
                    action="place_order",
                    token=token,
                    secret=SECRET,
                )
                await validated.wait()
                return await consume_confirmation_token(request_session, token=token)

    tasks = [asyncio.create_task(consume()) for _ in range(2)]
    results = await asyncio.gather(*tasks)

    try:
        assert sorted(results) == [False, True], "one token was consumed twice"
    finally:
        async with session_factory() as cleanup:
            async with cleanup.begin():
                await cleanup.execute(
                    delete(ConfirmationToken).where(ConfirmationToken.session_id == session_id)
                )
                await cleanup.execute(delete(Cart).where(Cart.session_id == session_id))
                await cleanup.execute(delete(Product).where(Product.id == product_id))
                await cleanup.execute(delete(Session).where(Session.id == session_id))
                await cleanup.execute(delete(Merchant).where(Merchant.id == merchant_id))
