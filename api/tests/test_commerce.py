from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.commerce.cart import add_to_cart, apply_offer, create_cart, recompute_cart_totals
from app.commerce.fingerprint import FingerprintItem, cart_fingerprint
from app.commerce.orders import capture_order_stock, create_order, release_order_reservation
from app.db.models import Cart, CartItem, Merchant, Product, ProductVariant, Session
from app.db.seed.catalog import MERCHANT_ID
from app.db.session import get_session_factory
from app.domain.enums import OrderStatus, SessionOutcome, VariantAxis
from app.domain.errors import ValidationError


async def _new_cart(session: AsyncSession) -> Cart:
    commerce_session = Session(
        merchant_id=MERCHANT_ID,
        outcome=SessionOutcome.ACTIVE,
        is_demo=True,
    )
    session.add(commerce_session)
    await session.flush()
    return await create_cart(session, commerce_session.id, MERCHANT_ID)


async def _available_running_variant(session: AsyncSession) -> tuple[Product, ProductVariant]:
    row = (
        (
            await session.execute(
                select(Product, ProductVariant)
                .join(ProductVariant, ProductVariant.product_id == Product.id)
                .where(
                    Product.category == "running_shoes",
                    Product.price_paise >= 400_000,
                    ProductVariant.stock_qty >= 2,
                )
                .order_by(Product.sku, ProductVariant.size)
            )
        )
        .tuples()
        .first()
    )
    assert row is not None
    return row


@pytest.mark.asyncio
async def test_cart_snapshots_price_and_recomputes_paise_totals(
    seeded_catalog: AsyncSession,
) -> None:
    cart = await _new_cart(seeded_catalog)
    product, variant = await _available_running_variant(seeded_catalog)

    await add_to_cart(seeded_catalog, cart.id, variant.id, 2)
    product.price_paise += 100_000
    totals = await recompute_cart_totals(seeded_catalog, cart)

    assert totals.subtotal_paise == 2 * (product.price_paise - 100_000)
    assert totals.discount_paise == 0
    assert totals.total_paise == totals.subtotal_paise


@pytest.mark.asyncio
async def test_offer_discount_is_recomputed_and_capped_in_paise(
    seeded_catalog: AsyncSession,
) -> None:
    cart = await _new_cart(seeded_catalog)
    _, variant = await _available_running_variant(seeded_catalog)
    await add_to_cart(seeded_catalog, cart.id, variant.id, 2)
    await apply_offer(seeded_catalog, cart.id, "runstrong10")

    assert cart.subtotal_paise >= 800_000
    assert cart.discount_paise == 60_000
    assert cart.total_paise == cart.subtotal_paise - cart.discount_paise


def test_cart_fingerprint_changes_only_for_purchase_commitment_facts() -> None:
    first = FingerprintItem(uuid.UUID(int=1), 1, 429_900)
    second = FingerprintItem(uuid.UUID(int=2), 2, 49_900)
    original = cart_fingerprint([first, second], 529_700)

    assert original == cart_fingerprint([second, first], 529_700)
    assert original != cart_fingerprint(
        [FingerprintItem(first.variant_id, 2, 429_900), second], 959_600
    )
    assert original != cart_fingerprint(
        [FingerprintItem(first.variant_id, 1, 430_000), second], 529_800
    )
    assert original != cart_fingerprint([first], 429_900)


@pytest.mark.asyncio
async def test_stock_reservation_releases_on_failure_and_captures_on_payment(
    seeded_catalog: AsyncSession,
) -> None:
    cart = await _new_cart(seeded_catalog)
    _, variant = await _available_running_variant(seeded_catalog)
    original_stock = variant.stock_qty

    await add_to_cart(seeded_catalog, cart.id, variant.id, 1)
    failed_order = await create_order(seeded_catalog, cart.id)
    await seeded_catalog.refresh(variant)
    assert variant.reserved_qty == 1
    await release_order_reservation(seeded_catalog, failed_order.id, OrderStatus.FAILED)
    await seeded_catalog.refresh(variant)
    assert (variant.stock_qty, variant.reserved_qty) == (original_stock, 0)

    paid_order = await create_order(seeded_catalog, cart.id)
    await capture_order_stock(seeded_catalog, paid_order.id)
    await seeded_catalog.refresh(variant)
    assert (variant.stock_qty, variant.reserved_qty) == (original_stock - 1, 0)


@pytest.mark.asyncio
async def test_inventory_database_constraints_reject_invalid_stock(
    seeded_catalog: AsyncSession,
) -> None:
    _, variant = await _available_running_variant(seeded_catalog)
    async with seeded_catalog.begin_nested():
        variant.stock_qty = -1
        with pytest.raises(IntegrityError):
            await seeded_catalog.flush()
    await seeded_catalog.refresh(variant)
    assert variant.stock_qty >= 0


@pytest.mark.asyncio
async def test_concurrent_last_unit_add_to_same_cart_never_exceeds_stock() -> None:
    """The cart lock serialises duplicate adds; actual stock reservation stays at order creation."""
    merchant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    product_id = uuid.uuid4()
    variant_id = uuid.uuid4()
    cart_id: uuid.UUID | None = None
    session_factory = get_session_factory()

    async with session_factory() as setup_session:
        async with setup_session.begin():
            setup_session.add(Merchant(id=merchant_id, name=f"Test Merchant {merchant_id}"))
            setup_session.add(
                Session(
                    id=session_id,
                    merchant_id=merchant_id,
                    outcome=SessionOutcome.ACTIVE,
                )
            )
            setup_session.add(
                Product(
                    id=product_id,
                    merchant_id=merchant_id,
                    sku=f"TEST-PRODUCT-{product_id}",
                    title="Single Unit Runner",
                    brand="Test Brand",
                    category="running_shoes",
                    subcategory="test",
                    price_paise=100_000,
                    description="Test product",
                    attrs={"use_case": "daily_easy_runs", "gender": "unisex"},
                )
            )
            setup_session.add(
                ProductVariant(
                    id=variant_id,
                    product_id=product_id,
                    sku=f"TEST-VARIANT-{variant_id}",
                    axis=VariantAxis.FOOTWEAR_SIZE,
                    size="UK 9",
                    colour="Black",
                    stock_qty=1,
                    reserved_qty=0,
                )
            )
            cart = await create_cart(setup_session, session_id, merchant_id)
            cart_id = cart.id

    assert cart_id is not None
    start = asyncio.Event()

    async def add_one() -> str:
        await start.wait()
        try:
            async with session_factory() as transaction_session:
                async with transaction_session.begin():
                    await add_to_cart(transaction_session, cart_id, variant_id, 1)
            return "added"
        except ValidationError as error:
            assert error.code == "STOCK_UNAVAILABLE"
            return "rejected"

    first = asyncio.create_task(add_one())
    second = asyncio.create_task(add_one())
    start.set()
    results = await asyncio.gather(first, second)

    try:
        async with session_factory() as check_session:
            quantity = await check_session.scalar(
                select(CartItem.quantity).where(
                    CartItem.cart_id == cart_id, CartItem.variant_id == variant_id
                )
            )
        assert sorted(results) == ["added", "rejected"]
        assert quantity == 1
    finally:
        async with session_factory() as cleanup_session:
            async with cleanup_session.begin():
                await cleanup_session.execute(delete(Cart).where(Cart.id == cart_id))
                await cleanup_session.execute(delete(Product).where(Product.id == product_id))
                await cleanup_session.execute(delete(Session).where(Session.id == session_id))
                await cleanup_session.execute(delete(Merchant).where(Merchant.id == merchant_id))
