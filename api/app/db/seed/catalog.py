from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import cast

from sqlalchemy import delete, func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Merchant, Product, ProductVariant
from app.db.seed.offers import SEED_NAMESPACE, seed_offers, stable_id
from app.db.session import get_session_factory
from app.domain.enums import VariantAxis

DATA_FILE = Path(__file__).with_name("data") / "products.json"
MERCHANT_ID = stable_id("merchant:stride-and-stone")
FOOTWEAR_CATEGORIES = frozenset({"running_shoes", "training_shoes"})
VARIANT_OPTIONS = {
    "running_shoes": (
        VariantAxis.FOOTWEAR_SIZE,
        ("UK 6", "UK 7", "UK 8", "UK 9", "UK 10", "UK 11", "UK 12"),
    ),
    "training_shoes": (
        VariantAxis.FOOTWEAR_SIZE,
        ("UK 6", "UK 7", "UK 8", "UK 9", "UK 10", "UK 11", "UK 12"),
    ),
    "socks": (VariantAxis.APPAREL_SIZE, ("S", "M", "L", "XL")),
    "apparel": (VariantAxis.APPAREL_SIZE, ("S", "M", "L", "XL")),
    "insoles": (VariantAxis.APPAREL_SIZE, ("S", "M", "L")),
    "recovery": (VariantAxis.ONE_SIZE, ("One Size",)),
    "hydration": (VariantAxis.ONE_SIZE, ("One Size",)),
    "gps_watches": (VariantAxis.ONE_SIZE, ("One Size",)),
}
COLOURS_BY_CATEGORY = {
    "running_shoes": ("Graphite", "Mist Blue", "Cinder Orange"),
    "training_shoes": ("Charcoal", "Moss", "Clay"),
    "socks": ("Cloud", "Cobalt", "Ember"),
    "apparel": ("Juniper", "Sand", "Night"),
    "insoles": ("Slate", "Coral", "Lime"),
    "recovery": ("Basalt", "Forest"),
    "hydration": ("Clear", "Ocean"),
    "gps_watches": ("Black", "Silver"),
}
EXPANSION_TARGETS = {
    "running_shoes": 46,
    "training_shoes": 15,
    "socks": 8,
    "insoles": 7,
    "apparel": 11,
    "recovery": 7,
    "hydration": 7,
    "gps_watches": 7,
}
RUNNING_USE_CASES = ("daily_easy_runs", "speed", "trail")
RUNNING_ARCH_SUPPORT = ("neutral", "stability", "motion_control")


def load_products() -> list[dict[str, object]]:
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(product, dict) for product in payload):
        raise ValueError("Seed catalog must contain a JSON array of product objects")
    raw_products = [cast(dict[str, object], product) for product in payload]
    return [normalise_product(product) for product in expand_catalog(raw_products)]


def expand_catalog(products: list[dict[str, object]]) -> list[dict[str, object]]:
    """Create deterministic depth from curated product archetypes.

    The source data is intentionally hand-authored archetypes; the expansion supplies the
    realistic breadth needed to test ranking without maintaining 140 nearly-identical JSON rows.
    """
    expanded = list(products)
    for category, quantity in EXPANSION_TARGETS.items():
        templates = [product for product in products if product["category"] == category]
        for index in range(quantity):
            template = templates[index % len(templates)]
            raw_attrs = dict(cast(dict[str, object], template["attrs"]))
            footwear = raw_attrs.pop("footwear", None)
            if isinstance(footwear, dict):
                raw_attrs.update(footwear)
            template_price = template["price_paise"]
            assert isinstance(template_price, int)
            price_paise = template_price + ((index % 12) - 4) * 29_900
            if category == "running_shoes":
                use_case = RUNNING_USE_CASES[index % len(RUNNING_USE_CASES)]
                arch_support = RUNNING_ARCH_SUPPORT[index % len(RUNNING_ARCH_SUPPORT)]
                raw_attrs["use_case"] = use_case
                raw_attrs["arch_support"] = arch_support
                raw_attrs["terrain"] = "trail" if use_case == "trail" else "road"
                raw_attrs["cushioning"] = ("low", "medium", "high")[index % 3]
                raw_attrs["drop_mm"] = (4, 6, 8, 10)[index % 4]
                price_paise = max(249_900, price_paise)
                if arch_support == "motion_control":
                    price_paise = max(350_000, price_paise)
            else:
                price_paise = max(39_900, price_paise)

            edition = index + 1
            expanded.append(
                {
                    **template,
                    "sku": f"{template['sku']}-E{edition:02d}",
                    "title": f"{template['title']} Series {edition}",
                    "subcategory": f"{template['subcategory']}_series",
                    "price_paise": price_paise,
                    "description": (
                        f"{template['description']} Series {edition} adds a distinct fit "
                        "and finish "
                        "for the Stride & Stone catalog."
                    ),
                    "attrs": raw_attrs,
                }
            )
    expanded.append(
        {
            "sku": "RIV-BRIDGE-OOS",
            "title": "BridgeGuard Daily",
            "brand": "Rivana Run",
            "category": "running_shoes",
            "subcategory": "road_stability",
            "price_paise": 469_900,
            "description": (
                "An in-budget stability road runner for daily five-kilometre sessions, "
                "deliberately unavailable in UK 9."
            ),
            "attrs": {
                "use_case": "daily_easy_runs",
                "arch_support": "stability",
                "cushioning": "medium",
                "drop_mm": 8,
                "weight_g": 274,
                "terrain": "road",
                "gender": "unisex",
                "rating": 4.5,
                "review_count": 228,
            },
        }
    )
    return expanded


def normalise_product(product: dict[str, object]) -> dict[str, object]:
    """Persist shared attributes separately from footwear-only retrieval facts."""
    raw_attrs = product["attrs"]
    assert isinstance(raw_attrs, dict)
    attrs: dict[str, object] = {
        key: raw_attrs[key] for key in ("use_case", "gender", "rating", "review_count")
    }
    if product["category"] in FOOTWEAR_CATEGORIES:
        footwear = raw_attrs.get("footwear")
        attrs["footwear"] = (
            footwear
            if isinstance(footwear, dict)
            else {
                key: raw_attrs[key]
                for key in ("arch_support", "cushioning", "drop_mm", "weight_g", "terrain")
            }
        )
    return {**product, "attrs": attrs}


def variants_for(product: dict[str, object]) -> tuple[VariantAxis, tuple[str, ...]]:
    category = str(product["category"])
    try:
        return VARIANT_OPTIONS[category]
    except KeyError as error:
        raise ValueError(f"Unsupported product category for variants: {category}") from error


def product_colour(product: dict[str, object]) -> str:
    category = str(product["category"])
    colours = COLOURS_BY_CATEGORY[category]
    return colours[uuid.uuid5(SEED_NAMESPACE, f"colour:{product['sku']}").int % len(colours)]


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
        ("RIV-BRIDGE-OOS", "UK 9"),
        ("KORA-SOCK-CREW", "M"),
        ("RIV-SHORT-5", "L"),
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
    fields: list[object] = [
        product["title"],
        product["brand"],
        product["category"],
        attrs["use_case"],
        product["description"],
    ]
    footwear = attrs.get("footwear")
    if isinstance(footwear, dict):
        fields.extend(footwear.values())
    return " ".join(str(value) for value in fields)


async def seed_catalog(session: AsyncSession | None = None) -> None:
    """Load the catalog into an owned session, or a caller-managed test transaction."""
    products = load_products()
    if session is None:
        async with get_session_factory()() as owned_session:
            await _seed_catalog(owned_session, products)
            await owned_session.commit()
    else:
        await _seed_catalog(session, products)


async def _seed_catalog(session: AsyncSession, products: list[dict[str, object]]) -> None:
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

    product_ids = [stable_id(f"product:{product['sku']}") for product in products]
    await session.execute(
        delete(Product).where(
            Product.merchant_id == MERCHANT_ID,
            Product.is_demo.is_(True),
            Product.id.not_in(product_ids),
        )
    )
    await session.execute(delete(ProductVariant).where(ProductVariant.product_id.in_(product_ids)))

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
                    key: value for key, value in values.items() if key not in {"id", "merchant_id"}
                },
            )
        )
        axis, values_for_axis = variants_for(product)
        for size in values_for_axis:
            variant_sku = f"{sku}-{size.replace(' ', '').replace('UK', 'U').replace(' ', '')}"
            variant = {
                "id": stable_id(f"variant:{sku}:{size}"),
                "product_id": product_id,
                "sku": variant_sku,
                "axis": axis.value,
                "size": size,
                "colour": product_colour(product),
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


def main() -> None:
    asyncio.run(seed_catalog())


if __name__ == "__main__":
    main()
