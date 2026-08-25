from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import cast

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert

from app.db.models import Merchant, Product, ProductVariant
from app.db.seed.offers import SEED_NAMESPACE, seed_offers, stable_id
from app.db.session import get_session_factory

DATA_FILE = Path(__file__).with_name("data") / "products.json"
MERCHANT_ID = stable_id("merchant:stride-and-stone")
SIZES = ("UK 6", "UK 7", "UK 8", "UK 9", "UK 10", "UK 11", "UK 12")


def load_products() -> list[dict[str, object]]:
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(product, dict) for product in payload):
        raise ValueError("Seed catalog must contain a JSON array of product objects")
    return cast(list[dict[str, object]], payload)


# Products the scripted demo walks through. These must never be out of stock in any
# size: a hash-random zero here silently breaks the demo (see PROJECT_STATUS.md).
DEMO_PATH_SKUS = frozenset(
    {
        "RIV-STRIDE-34",
        "RIV-HARBOR-2",
        "KORA-ALIGN-3",
        "VAYU-CONTROL-1",
        "VAYU-ANCHOR-X",
        "RIV-SOCK-AB",
        "RIV-ORTHO-1",
        "RIV-ROLLER-CORE",
    }
)

# Chosen, not hashed: the STOCK_AVAILABLE policy rule and check_inventory need a
# predictable out-of-stock variant on an in-budget shoe the agent will plausibly surface.
# This is the complete set of zero-stock variants in the catalog.
DELIBERATE_OUT_OF_STOCK = frozenset(
    {
        ("KORA-CLOUD-5", "UK 9"),
        ("KORA-CLOUD-5", "UK 10"),
        ("VAYU-PULSE-4", "UK 9"),
        ("RIV-METRO-2", "UK 8"),
        ("KORA-SWIFT-2", "UK 11"),
        ("KORA-SOCK-CREW", "UK 8"),
        ("RIV-SHORT-5", "UK 10"),
    }
)


def stable_stock(product_sku: str, size: str) -> int:
    """Return uneven but repeatable stock.

    Out-of-stock variants are declared, never hash-derived, so the demo path and the
    inventory-policy path are both reproducible instead of accidents of a UUID digest.
    """
    if (product_sku, size) in DELIBERATE_OUT_OF_STOCK:
        return 0
    digest = uuid.uuid5(SEED_NAMESPACE, f"stock:{product_sku}:{size}").int
    if product_sku in DEMO_PATH_SKUS:
        return 4 + digest % 21
    return 1 + digest % 24


def product_document(product: dict[str, object]) -> str:
    attrs = product["attrs"]
    assert isinstance(attrs, dict)
    return " ".join(
        str(value)
        for value in (
            product["title"],
            product["brand"],
            product["category"],
            attrs["use_case"],
            attrs["arch_support"],
            attrs["terrain"],
            product["description"],
        )
    )


async def seed_catalog() -> None:
    products = load_products()
    async with get_session_factory()() as session:
        merchant = {
            "id": MERCHANT_ID,
            "name": "Stride & Stone",
            "max_cart_value_paise": 2_000_000,
            "is_demo": True,
        }
        statement = insert(Merchant).values(**merchant)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[Merchant.id],
                set_={
                    "name": merchant["name"],
                    "max_cart_value_paise": merchant["max_cart_value_paise"],
                    "is_demo": True,
                },
            )
        )

        for product in products:
            sku = str(product["sku"])
            product_id = stable_id(f"product:{sku}")
            values = {
                **product,
                "id": product_id,
                "merchant_id": MERCHANT_ID,
                "is_demo": True,
            }
            statement = insert(Product).values(**values)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[Product.id],
                    set_={
                        key: value
                        for key, value in values.items()
                        if key not in {"id", "merchant_id"}
                    },
                )
            )
            for size in SIZES:
                variant_sku = f"{sku}-{size.replace(' ', '').replace('UK', 'U')}"
                variant = {
                    "id": stable_id(f"variant:{sku}:{size}"),
                    "product_id": product_id,
                    "sku": variant_sku,
                    "size": size,
                    "colour": "Graphite",
                    "stock_qty": stable_stock(sku, size),
                    "reserved_qty": 0,
                    "is_demo": True,
                }
                statement = insert(ProductVariant).values(**variant)
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[ProductVariant.id],
                        set_={
                            key: value
                            for key, value in variant.items()
                            if key not in {"id", "product_id"}
                        },
                    )
                )

        for product in products:
            sku = str(product["sku"])
            await session.execute(
                update(Product)
                .where(Product.id == stable_id(f"product:{sku}"))
                .values(search_tsv=func.to_tsvector("english", product_document(product)))
            )
        await seed_offers(session, MERCHANT_ID)
        await session.commit()


def main() -> None:
    asyncio.run(seed_catalog())


if __name__ == "__main__":
    main()
