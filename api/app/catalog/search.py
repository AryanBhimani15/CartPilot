from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.documents import product_document_from_values
from app.catalog.embeddings import EmbeddingProvider, get_embedding_provider
from app.catalog.index import VectorIndex, get_shared_vector_index
from app.catalog.ranking import business_rerank_bonus, reciprocal_rank_fusion
from app.config import Settings, get_settings
from app.db.models import Product, ProductEmbedding, ProductVariant


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Constraints which are always resolved by SQL, never by rank score."""

    max_price_paise: int | None = None
    category: str | None = None
    in_stock: bool = True
    size: str | None = None
    brand: str | None = None
    gender: str | None = None

    def __post_init__(self) -> None:
        if self.max_price_paise is not None and self.max_price_paise < 0:
            raise ValueError("max_price_paise must be non-negative")


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    semantic: float
    lexical: float
    rrf: float
    business: float
    final: float


@dataclass(frozen=True, slots=True)
class SearchHit:
    product_id: uuid.UUID
    sku: str
    title: str
    brand: str
    category: str
    price_paise: int
    attrs: dict[str, Any]
    available_sizes: tuple[str, ...]
    match_reasons: tuple[str, ...]
    score_breakdown: ScoreBreakdown


@dataclass(frozen=True, slots=True)
class _Candidate:
    product: Product
    in_stock: bool
    available_sizes: tuple[str, ...]


def _document(product: Product) -> str:
    return product_document_from_values(
        title=product.title,
        brand=product.brand,
        category=product.category,
        subcategory=product.subcategory,
        description=product.description,
        attrs=product.attrs,
    )


def _content_hash(document: str) -> str:
    return hashlib.sha256(document.encode("utf-8")).hexdigest()


async def ensure_product_embeddings(
    session: AsyncSession,
    products: Sequence[Product],
    provider: EmbeddingProvider,
) -> dict[uuid.UUID, list[float]]:
    """Load current document embeddings from cache and create only cache misses."""
    if not products:
        return {}
    documents = {product.id: _document(product) for product in products}
    hashes = {product_id: _content_hash(document) for product_id, document in documents.items()}
    rows = (
        await session.scalars(
            select(ProductEmbedding).where(
                ProductEmbedding.product_id.in_(documents), ProductEmbedding.model == provider.model
            )
        )
    ).all()
    cached = {
        embedding.product_id: list(embedding.vector)
        for embedding in rows
        if embedding.content_hash == hashes[embedding.product_id]
    }
    missing = [product for product in products if product.id not in cached]
    if missing:
        vectors = await provider.embed_documents([documents[product.id] for product in missing])
        if len(vectors) != len(missing):
            raise RuntimeError("Embedding provider returned an unexpected number of vectors")
        for product, vector in zip(missing, vectors, strict=True):
            if not vector:
                raise RuntimeError("Embedding provider returned an empty vector")
            session.add(
                ProductEmbedding(
                    product_id=product.id,
                    model=provider.model,
                    content_hash=hashes[product.id],
                    dim=len(vector),
                    vector=vector,
                    is_demo=product.is_demo,
                )
            )
            cached[product.id] = vector
        await session.flush()
    return cached


async def refresh_catalog_embeddings(
    session: AsyncSession,
    provider: EmbeddingProvider | None = None,
) -> None:
    """Refresh the current catalog after a seed or future catalog mutation."""
    settings = get_settings()
    active_provider = provider or get_embedding_provider(settings)
    products = (await session.scalars(select(Product))).all()
    embeddings = await ensure_product_embeddings(session, products, active_provider)
    get_shared_vector_index(settings.vector_backend).upsert(embeddings.items())


class CatalogSearchService:
    def __init__(
        self,
        session: AsyncSession,
        provider: EmbeddingProvider,
        index: VectorIndex,
    ) -> None:
        self._session = session
        self._provider = provider
        self._index = index

    async def _hard_filtered_candidates(self, filters: SearchFilters) -> list[_Candidate]:
        variant_query = select(ProductVariant.id).where(
            ProductVariant.product_id == Product.id,
            ProductVariant.stock_qty > ProductVariant.reserved_qty,
        )
        if filters.size is not None:
            variant_query = variant_query.where(ProductVariant.size == filters.size)
        in_stock = exists(variant_query)

        statement = select(Product, in_stock.label("in_stock"))
        if filters.max_price_paise is not None:
            statement = statement.where(Product.price_paise <= filters.max_price_paise)
        if filters.category is not None:
            statement = statement.where(Product.category == filters.category)
        if filters.brand is not None:
            statement = statement.where(Product.brand == filters.brand)
        if filters.gender is not None:
            statement = statement.where(Product.attrs["gender"].as_string() == filters.gender)
        if filters.in_stock:
            statement = statement.where(in_stock)
        statement = statement.order_by(Product.sku)

        candidates: list[_Candidate] = []
        for product, available in (await self._session.execute(statement)).all():
            sizes = (
                await self._session.scalars(
                    select(ProductVariant.size)
                    .where(
                        ProductVariant.product_id == product.id,
                        ProductVariant.stock_qty > ProductVariant.reserved_qty,
                    )
                    .order_by(ProductVariant.size)
                )
            ).all()
            candidates.append(
                _Candidate(product, bool(available), tuple(sizes)))
        return candidates

    async def search_products(
        self, query: str, filters: SearchFilters | None = None, k: int = 8
    ) -> list[SearchHit]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if k <= 0:
            return []
        active_filters = filters or SearchFilters()
        candidates = await self._hard_filtered_candidates(active_filters)
        if not candidates:
            return []

        products = [candidate.product for candidate in candidates]
        embeddings = await ensure_product_embeddings(self._session, products, self._provider)
        self._index.upsert(embeddings.items())
        query_vector = await self._provider.embed_query(query)
        semantic_results = self._index.search(query_vector, len(products), set(embeddings))
        semantic_scores = {result.product_id: result.score for result in semantic_results}

        tsquery = func.websearch_to_tsquery("english", query)
        lexical_score = func.ts_rank_cd(Product.search_tsv, tsquery).label("lexical_score")
        lexical_rows = (
            await self._session.execute(
                select(Product.id, lexical_score)
                .where(Product.id.in_(embeddings))
                .order_by(lexical_score.desc(), Product.sku)
            )
        ).all()
        lexical_positive = [
            (product_id, float(score))
            for product_id, score in lexical_rows
            if score is not None and float(score) > 0
        ]
        lexical_scores = dict(lexical_positive)
        fused = reciprocal_rank_fusion(
            (
                [result.product_id for result in semantic_results],
                [product_id for product_id, _ in lexical_positive],
            )
        )

        query_lower = query.lower()
        hits: list[SearchHit] = []
        for candidate in candidates:
            product = candidate.product
            attrs = product.attrs
            review_count = int(attrs.get("review_count", 0))
            business = business_rerank_bonus(
                in_stock=candidate.in_stock,
                review_count=review_count,
            )
            rrf = fused.get(product.id, 0.0)
            breakdown = ScoreBreakdown(
                semantic=semantic_scores.get(product.id, 0.0),
                lexical=lexical_scores.get(product.id, 0.0),
                rrf=rrf,
                business=business,
                final=rrf + business,
            )
            hits.append(
                SearchHit(
                    product_id=product.id,
                    sku=product.sku,
                    title=product.title,
                    brand=product.brand,
                    category=product.category,
                    price_paise=product.price_paise,
                    attrs=attrs,
                    available_sizes=candidate.available_sizes,
                    match_reasons=self._match_reasons(
                        product,
                        candidate,
                        active_filters,
                        query_lower,
                        breakdown.lexical,
                    ),
                    score_breakdown=breakdown,
                )
            )
        return sorted(hits, key=lambda hit: (-hit.score_breakdown.final, hit.sku))[:k]

    @staticmethod
    def _match_reasons(
        product: Product,
        candidate: _Candidate,
        filters: SearchFilters,
        query_lower: str,
        lexical_score: float,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if filters.max_price_paise is not None and product.price_paise <= filters.max_price_paise:
            reasons.append("Within your configured budget")
        if filters.category is not None and product.category == filters.category:
            reasons.append("Matches your selected category")
        if candidate.in_stock:
            if filters.size is not None and filters.size in candidate.available_sizes:
                reasons.append(f"Available in {filters.size}")
            else:
                reasons.append("Available to order")
        if filters.gender is not None and product.attrs.get("gender") == filters.gender:
            reasons.append("Matches your selected fit")
        footwear = product.attrs.get("footwear")
        if isinstance(footwear, Mapping):
            support = footwear.get("arch_support")
            if "flat feet" in query_lower and support in {"stability", "motion_control"}:
                reasons.append("Supportive build for flat feet")
            if "daily" in query_lower and product.attrs.get("use_case") == "daily_easy_runs":
                reasons.append("Built for daily easy runs")
        if lexical_score > 0:
            reasons.append("Exact catalog terms matched")
        return tuple(reasons)


def get_catalog_search_service(
    session: AsyncSession,
    settings: Settings | None = None,
) -> CatalogSearchService:
    active_settings = settings or get_settings()
    return CatalogSearchService(
        session=session,
        provider=get_embedding_provider(active_settings),
        index=get_shared_vector_index(active_settings.vector_backend),
    )
