from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Offer, Product, ProductVariant
from app.db.seed.catalog import (
    DATA_FILE,
    DELIBERATE_OUT_OF_STOCK,
    DEMO_PATH_SKUS,
    FOOTWEAR_CATEGORIES,
    load_products,
    product_document,
    seed_catalog,
)
from app.domain.enums import VariantAxis


async def table_counts(session: AsyncSession) -> tuple[int, int, int]:
    counts: list[int] = []
    for model in (Product, ProductVariant, Offer):
        count = await session.scalar(select(func.count()).select_from(model))
        assert count is not None
        counts.append(count)
    return (counts[0], counts[1], counts[2])


async def seeded_ids(session: AsyncSession) -> tuple[set[object], set[object], set[object]]:
    return (
        set((await session.scalars(select(Product.id))).all()),
        set((await session.scalars(select(ProductVariant.id))).all()),
        set((await session.scalars(select(Offer.id))).all()),
    )


@pytest.mark.asyncio
async def test_seed_catalog_is_idempotent_and_meets_demo_guarantees(
    seeded_catalog: AsyncSession,
) -> None:
    before = await table_counts(seeded_catalog)
    ids_before = await seeded_ids(seeded_catalog)
    await seed_catalog(seeded_catalog)
    products = (await seeded_catalog.scalars(select(Product))).all()
    variants = (await seeded_catalog.scalars(select(ProductVariant))).all()
    after = await table_counts(seeded_catalog)
    ids_after = await seeded_ids(seeded_catalog)

    assert before == after
    assert before[0] >= 140
    assert before[1] > before[0]
    assert before[2] == 3
    assert ids_before == ids_after
    category_counts: dict[str, int] = {}
    for product in products:
        category_counts[product.category] = category_counts.get(product.category, 0) + 1
    assert category_counts["running_shoes"] >= 50
    assert all(count >= 4 for count in category_counts.values())
    stock_by_product = {product.id: 0 for product in products}
    for variant in variants:
        stock_by_product[variant.product_id] += variant.stock_qty

    stability_under_budget = [
        product
        for product in products
        if product.category == "running_shoes"
        and product.price_paise <= 499_900
        and product.attrs["footwear"]["arch_support"] == "stability"
        and stock_by_product[product.id] > 0
    ]
    assert len(stability_under_budget) >= 3
    assert any(
        product.price_paise == 649_900 and product.attrs["footwear"]["arch_support"] == "stability"
        for product in products
    )
    assert (
        len(
            [
                product
                for product in products
                if product.category == "running_shoes"
                and product.price_paise <= 499_900
                and product.attrs["footwear"]["arch_support"] == "neutral"
            ]
        )
        >= 2
    )
    price_by_sku = {product.sku: product.price_paise for product in products}
    assert price_by_sku["RIV-SOCK-AB"] == 49_900
    assert price_by_sku["RIV-ORTHO-1"] == 89_900
    assert price_by_sku["RIV-ROLLER-CORE"] == 129_900
    assert not any(
        product.category == "running_shoes"
        and product.attrs["footwear"]["arch_support"] == "motion_control"
        and product.price_paise < 350_000
        for product in products
    )
    out_of_stock_near_miss = next(
        product for product in products if product.sku == "RIV-BRIDGE-OOS"
    )
    assert out_of_stock_near_miss.price_paise <= 499_900
    assert out_of_stock_near_miss.attrs["footwear"]["arch_support"] == "stability"
    assert out_of_stock_near_miss.attrs["use_case"] == "daily_easy_runs"


def test_seed_data_contains_no_real_world_trademarks() -> None:
    payload = json.dumps(json.loads(Path(DATA_FILE).read_text(encoding="utf-8"))).lower()
    prohibited = ("nike", "adidas", "asics", "puma", "reebok", "new balance")
    assert not any(mark in payload for mark in prohibited)


@pytest.mark.asyncio
async def test_demo_path_skus_are_in_stock_in_every_size(seeded_catalog: AsyncSession) -> None:
    """Aggregate stock > 0 is not enough: the demo picks one size, not the sum of sizes."""
    rows = (
        await seeded_catalog.execute(
            select(Product.sku, ProductVariant.size, ProductVariant.stock_qty).join(
                ProductVariant, ProductVariant.product_id == Product.id
            )
        )
    ).all()

    stock = {(sku, size): qty for sku, size, qty in rows}
    for sku in DEMO_PATH_SKUS:
        sku_quantities = [
            quantity for (variant_sku, _), quantity in stock.items() if variant_sku == sku
        ]
        assert sku_quantities
        assert all(quantity > 0 for quantity in sku_quantities)


@pytest.mark.asyncio
async def test_out_of_stock_variants_are_declared_not_incidental(
    seeded_catalog: AsyncSession,
) -> None:
    """Every stockout is declared, so inventory scenarios are reproducible."""
    rows = (
        await seeded_catalog.execute(
            select(Product.sku, ProductVariant.size, ProductVariant.stock_qty).join(
                ProductVariant, ProductVariant.product_id == Product.id
            )
        )
    ).all()

    zero = {(sku, size) for sku, size, qty in rows if qty == 0}
    assert zero == set(DELIBERATE_OUT_OF_STOCK), (
        "stockouts must be declared in DELIBERATE_OUT_OF_STOCK, not hash-derived"
    )


@pytest.mark.asyncio
async def test_variants_and_attributes_are_category_aware(seeded_catalog: AsyncSession) -> None:
    rows = (
        await seeded_catalog.execute(
            select(Product, ProductVariant).join(
                ProductVariant, ProductVariant.product_id == Product.id
            )
        )
    ).all()

    for product, variant in rows:
        if product.category in FOOTWEAR_CATEGORIES:
            assert variant.axis == VariantAxis.FOOTWEAR_SIZE
            assert variant.size.startswith("UK ")
            assert "footwear" in product.attrs
        else:
            assert not variant.size.startswith("UK ")
            assert variant.axis in {VariantAxis.APPAREL_SIZE, VariantAxis.ONE_SIZE}
            assert "footwear" not in product.attrs

    sock_variants = [variant for product, variant in rows if product.sku == "RIV-SOCK-AB"]
    assert {variant.size for variant in sock_variants} == {"S", "M", "L", "XL"}
    assert {variant.axis for variant in sock_variants} == {VariantAxis.APPAREL_SIZE}


def test_non_footwear_product_documents_exclude_footwear_vocabulary() -> None:
    gps_watch = next(product for product in load_products() if product["sku"] == "KORA-GPS-ONE")
    document = product_document(gps_watch).lower()
    assert not any(word in document for word in ("arch_support", "terrain", "drop", "cushioning"))


def test_generated_prose_never_contradicts_structured_attributes() -> None:
    """A description that disagrees with its own row poisons retrieval and the UI.

    The catalog expansion reassigns arch support and terrain on a cycle. If generated rows
    inherit an archetype's prose, the embedded text (T-004) and the computed match_reasons
    shown on a product card (D-012) end up asserting opposite things about the same shoe.
    """
    arch_vocabulary = {
        "neutral": "neutral",
        "stability": "stability",
        "motion_control": "motion-control",
    }
    conflicts: list[str] = []
    for product in load_products():
        if product["category"] != "running_shoes":
            continue
        footwear = product["attrs"]["footwear"]
        description = str(product["description"]).lower()
        for arch, token in arch_vocabulary.items():
            if token in description and arch != footwear["arch_support"]:
                conflicts.append(
                    f"{product['sku']}: text says {token}, "
                    f"attrs say {footwear['arch_support']}"
                )
        if "trail" in description and footwear["terrain"] != "trail":
            conflicts.append(
                f"{product['sku']}: text says trail, attrs say {footwear['terrain']}"
            )

    assert not conflicts, "description contradicts attributes:\n" + "\n".join(conflicts[:10])


def test_running_shoe_prices_are_not_clustered_on_a_floor() -> None:
    """Clamping to a price floor piles rows onto one value and makes budget edges look fake."""
    shoes = [product for product in load_products() if product["category"] == "running_shoes"]
    prices = [int(cast(int, product["price_paise"])) for product in shoes]
    assert len(set(prices)) >= int(len(shoes) * 0.8), "running-shoe prices are too clustered"


def test_motion_control_demand_gap_is_preserved() -> None:
    """T-010's unmet-demand insight needs a real gap, not an empty table."""
    shoes = [product for product in load_products() if product["category"] == "running_shoes"]
    motion_control = [
        product
        for product in shoes
        if product["attrs"]["footwear"]["arch_support"] == "motion_control"
    ]
    assert motion_control, "catalog must contain motion-control shoes"
    assert min(int(cast(int, p["price_paise"])) for p in motion_control) >= 350_000
