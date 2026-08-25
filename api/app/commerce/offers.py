from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.db.models import Offer
from app.domain.enums import OfferType


@dataclass(frozen=True, slots=True)
class OfferLine:
    sku: str
    category: str
    quantity: int
    unit_price_paise: int

    @property
    def line_total_paise(self) -> int:
        return self.quantity * self.unit_price_paise


@dataclass(frozen=True, slots=True)
class OfferCalculation:
    offer_id: object | None
    discount_paise: int


def _applies_to_line(scope: Mapping[str, Any], line: OfferLine) -> bool:
    skus = scope.get("skus")
    categories = scope.get("categories")
    if not skus and not categories:
        return True
    return (isinstance(skus, list) and line.sku in skus) or (
        isinstance(categories, list) and line.category in categories
    )


def calculate_offer(offer: Offer | None, lines: Iterable[OfferLine], subtotal_paise: int) -> int:
    """Calculate the only discount amount CartPilot is allowed to persist."""
    if offer is None or not offer.active or subtotal_paise < offer.min_cart_paise:
        return 0
    line_list = list(lines)
    applicable_subtotal = sum(
        line.line_total_paise
        for line in line_list
        if _applies_to_line(offer.applicable_scope, line)
    )
    if applicable_subtotal == 0:
        return 0
    if offer.offer_type == OfferType.PERCENTAGE:
        discount = applicable_subtotal * offer.value // 100
    elif offer.offer_type == OfferType.FIXED:
        discount = offer.value
    else:
        raise ValueError(f"Unsupported offer type: {offer.offer_type}")
    if offer.max_discount_paise is not None:
        discount = min(discount, offer.max_discount_paise)
    return min(discount, applicable_subtotal, subtotal_paise)
