from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Sequence


def reciprocal_rank_fusion(
    rankings: Iterable[Sequence[uuid.UUID]], *, rank_constant: int = 60
) -> dict[uuid.UUID, float]:
    """Fuse independently ranked semantic and lexical results without score-scale coupling."""
    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")
    fused: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for rank, product_id in enumerate(ranking, start=1):
            fused[product_id] = fused.get(product_id, 0.0) + 1.0 / (rank_constant + rank)
    return fused


def business_rerank_bonus(*, in_stock: bool, review_count: int) -> float:
    """Small transparent tie-breaker; it cannot defeat a hard filter or dominate RRF."""
    stock_bonus = 0.002 if in_stock else 0.0
    review_bonus = min(math.log1p(max(review_count, 0)), 8.0) / 100_000
    return stock_bonus + review_bonus
