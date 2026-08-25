from __future__ import annotations

import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Offer
from app.domain.enums import OfferType

SEED_NAMESPACE = uuid.UUID("b455c2ac-956e-4b8e-aab2-83c5e5b52ee6")


def stable_id(name: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, name)


async def seed_offers(session: AsyncSession, merchant_id: uuid.UUID) -> None:
    offers = (
        {
            "id": stable_id("offer:RUNSTRONG10"),
            "merchant_id": merchant_id,
            "code": "RUNSTRONG10",
            "offer_type": OfferType.PERCENTAGE.value,
            "value": 10,
            "min_cart_paise": 400_000,
            "max_discount_paise": 60_000,
            "applicable_scope": {"categories": ["running_shoes"]},
            "active": True,
            "is_demo": True,
        },
        {
            "id": stable_id("offer:SOCKPAIR"),
            "merchant_id": merchant_id,
            "code": "SOCKPAIR",
            "offer_type": OfferType.FIXED.value,
            "value": 10_000,
            "min_cart_paise": 90_000,
            "max_discount_paise": None,
            "applicable_scope": {"skus": ["RIV-SOCK-AB", "KORA-SOCK-CREW", "VAYU-SOCK-TRAIL"]},
            "active": True,
            "is_demo": True,
        },
        {
            "id": stable_id("offer:RECOVER150"),
            "merchant_id": merchant_id,
            "code": "RECOVER150",
            "offer_type": OfferType.FIXED.value,
            "value": 15_000,
            "min_cart_paise": 150_000,
            "max_discount_paise": None,
            "applicable_scope": {"categories": ["recovery", "insoles"]},
            "active": True,
            "is_demo": True,
        },
    )
    for offer in offers:
        statement = insert(Offer).values(**offer)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[Offer.id],
                set_={
                    key: value for key, value in offer.items() if key not in {"id", "merchant_id"}
                },
            )
        )
