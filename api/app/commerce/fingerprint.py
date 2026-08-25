from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FingerprintItem:
    variant_id: uuid.UUID
    quantity: int
    unit_price_paise: int


def cart_fingerprint(items: Iterable[FingerprintItem], total_paise: int) -> str:
    """Return a stable hash of the only facts that define a purchase commitment."""
    if total_paise < 0:
        raise ValueError("total_paise must be non-negative")
    ordered_items = sorted(items, key=lambda item: str(item.variant_id))
    if any(item.quantity <= 0 or item.unit_price_paise < 0 for item in ordered_items):
        raise ValueError("Cart fingerprint items must have positive quantities and paise prices")
    canonical_items: list[dict[str, int | str]] = [
        {
            "quantity": item.quantity,
            "unit_price_paise": item.unit_price_paise,
            "variant_id": str(item.variant_id),
        }
        for item in ordered_items
    ]
    payload = {"items": canonical_items, "total_paise": total_paise}
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
