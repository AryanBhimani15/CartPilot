from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.embeddings import DeterministicEmbeddingProvider
from app.catalog.index import NumpyVectorIndex
from app.catalog.search import CatalogSearchService, SearchFilters
from app.db.models import Product, ProductEmbedding, ProductVariant
from app.db.seed.catalog import seed_catalog


def search_service(session: AsyncSession) -> CatalogSearchService:
    return CatalogSearchService(
        session=session,
        provider=DeterministicEmbeddingProvider(),
        index=NumpyVectorIndex(),
    )


@pytest.mark.asyncio
async def test_hybrid_search_respects_budget_stock_and_flat_feet_intent(
    seeded_catalog: AsyncSession,
) -> None:
    hits = await search_service(seeded_catalog).search_products(
        "running shoes under ₹5,000 for daily 5 km runs, flat feet",
        SearchFilters(max_price_paise=500_000, category="running_shoes", in_stock=True),
        k=8,
    )

    assert len(hits) >= 3
    assert all(hit.price_paise <= 500_000 for hit in hits)
    assert all(hit.available_sizes for hit in hits)
    assert (
        sum(
            hit.attrs.get("footwear", {}).get("arch_support") != "neutral"
            for hit in hits
        )
        >= 2
    )
    assert any("Supportive build for flat feet" in hit.match_reasons for hit in hits)


@pytest.mark.asyncio
async def test_over_budget_stability_shoe_cannot_bypass_sql_filter(
    seeded_catalog: AsyncSession,
) -> None:
    over_budget = (
        await seeded_catalog.scalars(
            select(Product).where(
                Product.price_paise == 649_900,
                Product.attrs["footwear"]["arch_support"].as_string() == "stability",
            )
        )
    ).all()
    assert over_budget

    hits = await search_service(seeded_catalog).search_products(
        "stability shoe for flat feet",
        SearchFilters(max_price_paise=500_000, category="running_shoes", in_stock=True),
        k=40,
    )

    returned_ids = {hit.product_id for hit in hits}
    assert all(product.id not in returned_ids for product in over_budget)
    assert all(hit.price_paise <= 500_000 for hit in hits)


@pytest.mark.asyncio
async def test_gps_watch_uses_lexical_arm_and_remains_network_free(
    seeded_catalog: AsyncSession,
) -> None:
    hits = await search_service(seeded_catalog).search_products(
        "GPS watch", SearchFilters(in_stock=True), k=8
    )

    assert hits
    assert hits[0].category == "gps_watches"
    assert hits[0].score_breakdown.lexical > 0
    assert any(hit.score_breakdown.lexical > 0 for hit in hits)


@pytest.mark.asyncio
async def test_size_is_a_hard_stock_filter(seeded_catalog: AsyncSession) -> None:
    hits = await search_service(seeded_catalog).search_products(
        "daily stability runner",
        SearchFilters(category="running_shoes", size="UK 9", in_stock=True),
        k=40,
    )

    assert hits
    assert all("UK 9" in hit.available_sizes for hit in hits)
    out_of_stock = (
        await seeded_catalog.scalars(
            select(ProductVariant.product_id).where(
                ProductVariant.size == "UK 9", ProductVariant.stock_qty == 0
            )
        )
    ).all()
    assert all(hit.product_id not in set(out_of_stock) for hit in hits)


@pytest.mark.asyncio
async def test_seed_reuses_content_hash_embedding_cache(seeded_catalog: AsyncSession) -> None:
    initial = await seeded_catalog.scalar(select(func.count()).select_from(ProductEmbedding))
    products = await seeded_catalog.scalar(select(func.count()).select_from(Product))
    assert initial == products

    await seed_catalog(seeded_catalog)

    repeated = await seeded_catalog.scalar(select(func.count()).select_from(ProductEmbedding))
    assert repeated == initial
