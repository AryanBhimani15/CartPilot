from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.search import (
    CatalogSearchService,
    ScoreBreakdown,
    SearchFilters,
    SearchHit,
    get_catalog_search_service,
)
from app.db.session import get_db_session

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


class ScoreBreakdownResponse(BaseModel):
    semantic: float
    lexical: float
    rrf: float
    business: float
    final: float


class SearchHitResponse(BaseModel):
    product_id: uuid.UUID
    sku: str
    title: str
    brand: str
    category: str
    price_paise: int
    attrs: dict[str, Any]
    available_sizes: list[str]
    match_reasons: list[str]
    score_breakdown: ScoreBreakdownResponse


def _score_response(score: ScoreBreakdown) -> ScoreBreakdownResponse:
    return ScoreBreakdownResponse(
        semantic=score.semantic,
        lexical=score.lexical,
        rrf=score.rrf,
        business=score.business,
        final=score.final,
    )


def _response(hit: SearchHit) -> SearchHitResponse:
    return SearchHitResponse(
        product_id=hit.product_id,
        sku=hit.sku,
        title=hit.title,
        brand=hit.brand,
        category=hit.category,
        price_paise=hit.price_paise,
        attrs=hit.attrs,
        available_sizes=list(hit.available_sizes),
        match_reasons=list(hit.match_reasons),
        score_breakdown=_score_response(hit.score_breakdown),
    )


async def _search_service(
    session: AsyncSession = Depends(get_db_session),
) -> CatalogSearchService:
    return get_catalog_search_service(session)


@router.get("/products/search", response_model=list[SearchHitResponse])
async def search_products(
    q: str = Query(min_length=1, max_length=500),
    max_price_paise: int | None = Query(default=None, ge=0),
    category: str | None = None,
    in_stock: bool = True,
    size: str | None = None,
    brand: str | None = None,
    gender: str | None = None,
    k: int = Query(default=8, ge=1, le=40),
    service: CatalogSearchService = Depends(_search_service),
) -> list[SearchHitResponse]:
    """Return products after SQL constraints, hybrid RRF and transparent re-ranking."""
    filters = SearchFilters(
        max_price_paise=max_price_paise,
        category=category,
        in_stock=in_stock,
        size=size,
        brand=brand,
        gender=gender,
    )
    return [_response(hit) for hit in await service.search_products(q, filters, k)]
