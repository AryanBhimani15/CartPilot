from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commerce.offers import OfferLine, calculate_offer
from app.db.models import Cart, CartItem, Offer, Order, Product, ProductVariant, Session
from app.domain.enums import OrderStatus
from app.domain.errors import NotFoundError, ValidationError


@dataclass(frozen=True, slots=True)
class CartTotals:
    subtotal_paise: int
    discount_paise: int
    total_paise: int


async def create_cart(session: AsyncSession, session_id: uuid.UUID, merchant_id: uuid.UUID) -> Cart:
    """Create the one cart allowed for a commerce session."""
    existing = await session.scalar(select(Cart).where(Cart.session_id == session_id))
    if existing is not None:
        return existing
    commerce_session = await session.scalar(
        select(Session).where(Session.id == session_id, Session.merchant_id == merchant_id)
    )
    if commerce_session is None:
        raise NotFoundError(
            "SESSION_NOT_FOUND", "The shopping session no longer exists.", "Start again."
        )
    cart = Cart(
        session_id=session_id,
        merchant_id=merchant_id,
        is_demo=commerce_session.is_demo,
        subtotal_paise=0,
        discount_paise=0,
        total_paise=0,
    )
    session.add(cart)
    await session.flush()
    return cart


async def _locked_cart(session: AsyncSession, cart_id: uuid.UUID) -> Cart:
    cart = await session.scalar(select(Cart).where(Cart.id == cart_id).with_for_update())
    if cart is None:
        raise NotFoundError("CART_NOT_FOUND", "The cart no longer exists.", "Create a new cart.")
    return cart


async def _ensure_cart_is_editable(session: AsyncSession, cart: Cart) -> None:
    active_order = await session.scalar(
        select(Order.id).where(
            Order.cart_id == cart.id,
            Order.status.in_((OrderStatus.CREATED, OrderStatus.PENDING_PAYMENT)),
        )
    )
    if active_order is not None:
        raise ValidationError(
            "CART_LOCKED_FOR_CHECKOUT",
            "This cart has an active checkout.",
            "Complete or cancel checkout before changing the cart.",
        )


async def _cart_lines(
    session: AsyncSession, cart_id: uuid.UUID
) -> list[tuple[CartItem, ProductVariant, Product]]:
    rows = (
        (
            await session.execute(
                select(CartItem, ProductVariant, Product)
                .join(ProductVariant, CartItem.variant_id == ProductVariant.id)
                .join(Product, ProductVariant.product_id == Product.id)
                .where(CartItem.cart_id == cart_id)
                .order_by(CartItem.variant_id)
            )
        )
        .tuples()
        .all()
    )
    return cast(list[tuple[CartItem, ProductVariant, Product]], rows)


async def recompute_cart_totals(session: AsyncSession, cart: Cart) -> CartTotals:
    """Recalculate totals from snapshot item prices and the database offer row."""
    rows = await _cart_lines(session, cart.id)
    lines = [
        OfferLine(
            sku=product.sku,
            category=product.category,
            quantity=item.quantity,
            unit_price_paise=item.unit_price_paise,
        )
        for item, _, product in rows
    ]
    subtotal = sum(line.line_total_paise for line in lines)
    offer = (
        await session.scalar(select(Offer).where(Offer.id == cart.offer_id))
        if cart.offer_id is not None
        else None
    )
    discount = calculate_offer(offer, lines, subtotal)
    cart.subtotal_paise = subtotal
    cart.discount_paise = discount
    cart.total_paise = subtotal - discount
    await session.flush()
    return CartTotals(subtotal, discount, subtotal - discount)


async def add_to_cart(
    session: AsyncSession, cart_id: uuid.UUID, variant_id: uuid.UUID, quantity: int
) -> Cart:
    """Snapshot a variant price after serialising updates to this cart.

    A cart is not an inventory reservation. The final stock reservation happens in
    `orders.create_order`; this check prevents a concurrent duplicate add to the same cart from
    claiming more than the currently sellable quantity.
    """
    if quantity <= 0:
        raise ValidationError(
            "INVALID_QUANTITY", "Quantity must be positive", "Choose at least one item."
        )
    cart = await _locked_cart(session, cart_id)
    await _ensure_cart_is_editable(session, cart)
    variant_and_product = await session.execute(
        select(ProductVariant, Product)
        .join(Product, ProductVariant.product_id == Product.id)
        .where(ProductVariant.id == variant_id, Product.merchant_id == cart.merchant_id)
        .with_for_update()
    )
    row = variant_and_product.one_or_none()
    if row is None:
        raise NotFoundError(
            "VARIANT_NOT_FOUND", "The selected product variant no longer exists.", "Search again."
        )
    variant, product = row
    item = await session.scalar(
        select(CartItem).where(CartItem.cart_id == cart.id, CartItem.variant_id == variant.id)
    )
    requested_quantity = quantity + (item.quantity if item is not None else 0)
    if variant.stock_qty - variant.reserved_qty < requested_quantity:
        raise ValidationError(
            "STOCK_UNAVAILABLE",
            "The requested quantity is no longer available.",
            "Choose an in-stock size or reduce the quantity.",
        )
    if item is None:
        session.add(
            CartItem(
                cart_id=cart.id,
                variant_id=variant.id,
                quantity=quantity,
                unit_price_paise=product.price_paise,
                is_demo=cart.is_demo,
            )
        )
    else:
        item.quantity = requested_quantity
    await session.flush()
    await recompute_cart_totals(session, cart)
    return cart


async def remove_from_cart(
    session: AsyncSession, cart_id: uuid.UUID, variant_id: uuid.UUID, quantity: int | None = None
) -> Cart:
    cart = await _locked_cart(session, cart_id)
    await _ensure_cart_is_editable(session, cart)
    item = await session.scalar(
        select(CartItem).where(CartItem.cart_id == cart.id, CartItem.variant_id == variant_id)
    )
    if item is None:
        raise NotFoundError(
            "CART_ITEM_NOT_FOUND", "That item is not in the cart.", "Choose an item in the cart."
        )
    if quantity is None or quantity >= item.quantity:
        await session.delete(item)
    elif quantity <= 0:
        raise ValidationError(
            "INVALID_QUANTITY", "Quantity must be positive", "Choose at least one item."
        )
    else:
        item.quantity -= quantity
    await session.flush()
    await recompute_cart_totals(session, cart)
    return cart


async def apply_offer(session: AsyncSession, cart_id: uuid.UUID, code: str) -> Cart:
    """Attach a validated database offer; callers never supply a discount amount."""
    cart = await _locked_cart(session, cart_id)
    await _ensure_cart_is_editable(session, cart)
    offer = await session.scalar(
        select(Offer).where(
            Offer.merchant_id == cart.merchant_id,
            Offer.code == code.upper(),
            Offer.active.is_(True),
        )
    )
    if offer is None:
        raise ValidationError(
            "OFFER_INVALID", "That offer is unavailable.", "Try an available offer code."
        )
    cart.offer_id = offer.id
    await recompute_cart_totals(session, cart)
    return cart
