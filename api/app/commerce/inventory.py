from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProductVariant
from app.domain.errors import NotFoundError, ValidationError


@dataclass(frozen=True, slots=True)
class StockReservation:
    variant_id: uuid.UUID
    quantity: int


def _normalise_reservations(reservations: Iterable[StockReservation]) -> list[StockReservation]:
    quantities: dict[uuid.UUID, int] = {}
    for reservation in reservations:
        if reservation.quantity <= 0:
            raise ValidationError(
                "INVALID_QUANTITY", "Quantity must be positive", "Choose at least one item."
            )
        quantities[reservation.variant_id] = (
            quantities.get(reservation.variant_id, 0) + reservation.quantity
        )
    return [
        StockReservation(variant_id=variant_id, quantity=quantity)
        for variant_id, quantity in sorted(quantities.items(), key=lambda item: str(item[0]))
    ]


async def _locked_variants(
    session: AsyncSession, reservations: list[StockReservation]
) -> dict[uuid.UUID, ProductVariant]:
    ids = [reservation.variant_id for reservation in reservations]
    variants = (
        await session.scalars(
            select(ProductVariant)
            .where(ProductVariant.id.in_(ids))
            .order_by(ProductVariant.id)
            .with_for_update()
        )
    ).all()
    by_id = {variant.id: variant for variant in variants}
    missing = next((variant_id for variant_id in ids if variant_id not in by_id), None)
    if missing is not None:
        raise NotFoundError(
            "VARIANT_NOT_FOUND", "The selected product variant no longer exists.", "Search again."
        )
    return by_id


async def reserve_stock(session: AsyncSession, reservations: Iterable[StockReservation]) -> None:
    """Atomically reserve inventory for order creation without decrementing sellable stock."""
    normalised = _normalise_reservations(reservations)
    if not normalised:
        return
    variants = await _locked_variants(session, normalised)
    for reservation in normalised:
        variant = variants[reservation.variant_id]
        if variant.stock_qty - variant.reserved_qty < reservation.quantity:
            raise ValidationError(
                "STOCK_UNAVAILABLE",
                "The requested quantity is no longer available.",
                "Choose an in-stock size or reduce the quantity.",
            )
    for reservation in normalised:
        variants[reservation.variant_id].reserved_qty += reservation.quantity
    await session.flush()


async def release_stock(session: AsyncSession, reservations: Iterable[StockReservation]) -> None:
    """Release a previously created order's reservation after failure or expiry."""
    normalised = _normalise_reservations(reservations)
    if not normalised:
        return
    variants = await _locked_variants(session, normalised)
    for reservation in normalised:
        variant = variants[reservation.variant_id]
        if variant.reserved_qty < reservation.quantity:
            raise RuntimeError("Cannot release stock that is not reserved")
    for reservation in normalised:
        variants[reservation.variant_id].reserved_qty -= reservation.quantity
    await session.flush()


async def capture_stock(session: AsyncSession, reservations: Iterable[StockReservation]) -> None:
    """Convert a reservation into a completed sale after a verified payment succeeds."""
    normalised = _normalise_reservations(reservations)
    if not normalised:
        return
    variants = await _locked_variants(session, normalised)
    for reservation in normalised:
        variant = variants[reservation.variant_id]
        if variant.reserved_qty < reservation.quantity or variant.stock_qty < reservation.quantity:
            raise RuntimeError("Cannot capture stock without its matching reservation")
    for reservation in normalised:
        variant = variants[reservation.variant_id]
        variant.reserved_qty -= reservation.quantity
        variant.stock_qty -= reservation.quantity
    await session.flush()
