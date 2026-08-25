from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commerce.cart import _cart_lines, _locked_cart, recompute_cart_totals
from app.commerce.fingerprint import FingerprintItem, cart_fingerprint
from app.commerce.inventory import StockReservation, capture_stock, release_stock, reserve_stock
from app.db.models import Cart, CartItem, Order, Product, ProductVariant
from app.domain.enums import OrderStatus
from app.domain.errors import NotFoundError, ValidationError


def _reservations(
    rows: list[tuple[CartItem, ProductVariant, Product]],
) -> list[StockReservation]:
    return [
        StockReservation(variant_id=item.variant_id, quantity=item.quantity) for item, _, _ in rows
    ]


async def create_order(session: AsyncSession, cart_id: uuid.UUID) -> Order:
    """Freeze a cart and atomically reserve its stock before any payment provider call."""
    cart = await _locked_cart(session, cart_id)
    active_order = await session.scalar(
        select(Order.id).where(
            Order.cart_id == cart.id,
            Order.status.in_((OrderStatus.CREATED, OrderStatus.PENDING_PAYMENT)),
        )
    )
    if active_order is not None:
        raise ValidationError(
            "ORDER_ALREADY_PENDING",
            "This cart already has an active order.",
            "Complete or cancel the existing checkout.",
        )
    totals = await recompute_cart_totals(session, cart)
    if totals.total_paise <= 0:
        raise ValidationError(
            "EMPTY_CART", "A cart needs an item before checkout.", "Add an item first."
        )
    rows = await _cart_lines(session, cart.id)
    await reserve_stock(session, _reservations(rows))
    fingerprint = cart_fingerprint(
        [
            FingerprintItem(
                variant_id=item.variant_id,
                quantity=item.quantity,
                unit_price_paise=item.unit_price_paise,
            )
            for item, _, _ in rows
        ],
        totals.total_paise,
    )
    order = Order(
        cart_id=cart.id,
        session_id=cart.session_id,
        merchant_id=cart.merchant_id,
        amount_paise=totals.total_paise,
        status=OrderStatus.CREATED,
        cart_fingerprint=fingerprint,
        is_demo=cart.is_demo,
    )
    session.add(order)
    await session.flush()
    return order


async def _locked_order(session: AsyncSession, order_id: uuid.UUID) -> Order:
    order = await session.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise NotFoundError(
            "ORDER_NOT_FOUND", "The order no longer exists.", "Start checkout again."
        )
    return order


async def release_order_reservation(
    session: AsyncSession, order_id: uuid.UUID, status: OrderStatus
) -> Order:
    """Release a failed or expired order's stock exactly once."""
    if status not in {OrderStatus.FAILED, OrderStatus.EXPIRED, OrderStatus.CANCELLED}:
        raise ValueError("Reservation release requires a terminal non-payment order status")
    order = await _locked_order(session, order_id)
    if order.status in {OrderStatus.FAILED, OrderStatus.EXPIRED, OrderStatus.CANCELLED}:
        return order
    if order.status == OrderStatus.PAID:
        raise ValidationError(
            "ORDER_ALREADY_PAID", "A paid order cannot be released.", "Review payment status."
        )
    cart = await session.scalar(select(Cart).where(Cart.id == order.cart_id))
    if cart is None:
        raise RuntimeError("Order cart is missing")
    await release_stock(session, _reservations(await _cart_lines(session, cart.id)))
    order.status = status
    await session.flush()
    return order


async def capture_order_stock(session: AsyncSession, order_id: uuid.UUID) -> Order:
    """Record payment success by converting the order's reservation into a sale."""
    order = await _locked_order(session, order_id)
    if order.status == OrderStatus.PAID:
        return order
    if order.status in {OrderStatus.FAILED, OrderStatus.EXPIRED, OrderStatus.CANCELLED}:
        raise ValidationError(
            "ORDER_NOT_PAYABLE", "This order is no longer payable.", "Create a new order."
        )
    cart = await session.scalar(select(Cart).where(Cart.id == order.cart_id))
    if cart is None:
        raise RuntimeError("Order cart is missing")
    await capture_stock(session, _reservations(await _cart_lines(session, cart.id)))
    order.status = OrderStatus.PAID
    await session.flush()
    return order
