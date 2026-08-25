from __future__ import annotations

import re

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.embeddings import DeterministicEmbeddingProvider, _tokens
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
        SearchFilters(
            max_price_paise=500_000,
            category="running_shoes",
            in_stock=True,
            arch_support=("stability", "motion_control"),
        ),
        k=8,
    )

    assert len(hits) >= 3
    assert all(hit.price_paise <= 500_000 for hit in hits)
    assert all(hit.available_sizes for hit in hits)
    # Arch support is a hard filter, so EVERY hit must satisfy it. Asserting "at least two"
    # would pass on a result set that is mostly neutral shoes — which is what this query
    # actually returned while arch support was only a soft ranking signal.
    assert all(
        hit.attrs["footwear"]["arch_support"] in {"stability", "motion_control"} for hit in hits
    )
    assert any("support as required" in reason for reason in hits[0].match_reasons)


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


def test_deterministic_provider_contains_no_catalog_vocabulary_mapping() -> None:
    """Guard against reintroducing shopper-phrase -> catalog-term injection.

    An earlier version expanded "flat feet" into the tokens "stability" and
    "motion_control" inside the embedding provider. That is a hand-written synonym table
    wearing a semantic-search costume, and because D-005 makes this provider the default
    for `make eval`, it would have manufactured CartPilot's relevance advantage in T-012.
    Tokens must be derivable from the input text alone.
    """
    query = "running shoes under 5,000 for daily 5 km runs, flat feet"
    produced = set(_tokens(query))
    from_text = set(re.findall(r"[a-z0-9_]+", query.lower()))
    injected = produced - from_text
    assert not injected, f"provider injected vocabulary absent from the query: {injected}"

    catalog_terms = (
        "stability",
        "motion_control",
        "daily_easy_runs",
        "running_shoes",
        "gps_watches",
    )
    for term in catalog_terms:
        assert term not in produced


@pytest.mark.asyncio
async def test_arch_support_filter_excludes_neutral_shoes(seeded_catalog: AsyncSession) -> None:
    """A flat-feet shopper must never be ranked into a neutral shoe."""
    hits = await search_service(seeded_catalog).search_products(
        "daily road running shoe",
        SearchFilters(
            category="running_shoes", in_stock=True, arch_support=("stability", "motion_control")
        ),
        k=40,
    )

    assert hits
    assert all(hit.attrs["footwear"]["arch_support"] != "neutral" for hit in hits)
