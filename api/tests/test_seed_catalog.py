from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.models import Offer, Product, ProductVariant
from app.db.seed.catalog import DATA_FILE, seed_catalog
from app.db.session import get_session_factory


async def table_counts() -> tuple[int, int, int]:
    async with get_session_factory()() as session:
        counts: list[int] = []
        for model in (Product, ProductVariant, Offer):
            count = await session.scalar(select(func.count()).select_from(model))
            assert count is not None
            counts.append(count)
    return (counts[0], counts[1], counts[2])


async def seeded_ids() -> tuple[set[object], set[object], set[object]]:
    async with get_session_factory()() as session:
        return (
            set((await session.scalars(select(Product.id))).all()),
            set((await session.scalars(select(ProductVariant.id))).all()),
            set((await session.scalars(select(Offer.id))).all()),
        )


@pytest.mark.asyncio
async def test_seed_catalog_is_idempotent_and_meets_demo_guarantees() -> None:
    await seed_catalog()
    before = await table_counts()
    ids_before = await seeded_ids()
    await seed_catalog()
    async with get_session_factory()() as session:
        products = (await session.scalars(select(Product))).all()
        variants = (await session.scalars(select(ProductVariant))).all()
    after = await table_counts()
    ids_after = await seeded_ids()

    assert before == after == (31, 217, 3)
    assert ids_before == ids_after
    stock_by_product = {product.id: 0 for product in products}
    for variant in variants:
        stock_by_product[variant.product_id] += variant.stock_qty

    stability_under_budget = [
        product
        for product in products
        if product.category == "running_shoes"
        and product.price_paise <= 499_900
        and product.attrs["arch_support"] == "stability"
        and stock_by_product[product.id] > 0
    ]
    assert len(stability_under_budget) >= 3
    assert any(
        product.price_paise == 649_900 and product.attrs["arch_support"] == "stability"
        for product in products
    )
    assert (
        len(
            [
                product
                for product in products
                if product.category == "running_shoes"
                and product.price_paise <= 499_900
                and product.attrs["arch_support"] == "neutral"
            ]
        )
        >= 2
    )
    price_by_sku = {product.sku: product.price_paise for product in products}
    assert price_by_sku["RIV-SOCK-AB"] == 49_900
    assert price_by_sku["RIV-ORTHO-1"] == 89_900
    assert price_by_sku["RIV-ROLLER-CORE"] == 129_900


def test_seed_data_contains_no_real_world_trademarks() -> None:
    payload = json.dumps(json.loads(Path(DATA_FILE).read_text(encoding="utf-8"))).lower()
    prohibited = ("nike", "adidas", "asics", "puma", "reebok", "new balance")
    assert not any(mark in payload for mark in prohibited)
