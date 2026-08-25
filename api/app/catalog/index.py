from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence, Set
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import numpy as np
import numpy.typing as npt

FloatVector = npt.NDArray[np.float32]


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    product_id: uuid.UUID
    score: float


class VectorIndex(Protocol):
    """Index boundary retained so pgvector can replace numpy at larger catalog sizes."""

    def upsert(self, vectors: Iterable[tuple[uuid.UUID, Sequence[float]]]) -> None: ...

    def search(
        self,
        query_vector: Sequence[float],
        k: int,
        ids_filter: Set[uuid.UUID] | None = None,
    ) -> list[VectorSearchResult]: ...


def _normalise(vector: Sequence[float]) -> FloatVector:
    array = np.asarray(vector, dtype=np.float32)
    if array.ndim != 1:
        raise ValueError("Embedding vectors must be one-dimensional")
    norm = float(np.linalg.norm(array))
    if norm == 0:
        return array
    return array / norm


class NumpyVectorIndex:
    """Exact in-process cosine search; optimal for CartPilot's ~140-product catalog."""

    def __init__(self) -> None:
        self._vectors: dict[uuid.UUID, FloatVector] = {}

    def upsert(self, vectors: Iterable[tuple[uuid.UUID, Sequence[float]]]) -> None:
        for product_id, vector in vectors:
            self._vectors[product_id] = _normalise(vector)

    def search(
        self,
        query_vector: Sequence[float],
        k: int,
        ids_filter: Set[uuid.UUID] | None = None,
    ) -> list[VectorSearchResult]:
        if k <= 0:
            return []
        product_ids = [
            product_id
            for product_id in self._vectors
            if ids_filter is None or product_id in ids_filter
        ]
        if not product_ids:
            return []
        query = _normalise(query_vector)
        vectors = np.stack([self._vectors[product_id] for product_id in product_ids])
        if vectors.shape[1] != query.shape[0]:
            raise ValueError("Query and catalog embedding dimensions must match")
        scores = vectors @ query
        count = min(k, len(product_ids))
        positions = np.argsort(-scores, kind="stable")[:count]
        return [
            VectorSearchResult(product_ids[int(position)], float(scores[int(position)]))
            for position in positions
        ]


class PgVectorIndex:
    """The pgvector implementation boundary, intentionally unavailable under Postgres 14.

    D-003 prohibits extension-dependent local setup. Keeping this concrete class lets a hosted
    pgvector deployment select VECTOR_BACKEND=pgvector explicitly instead of silently falling
    back to a different retrieval strategy.
    """

    def __init__(self) -> None:
        raise RuntimeError(
            "VECTOR_BACKEND=pgvector requires a pgvector-enabled deployment; "
            "local CartPilot uses VECTOR_BACKEND=numpy by design"
        )

    def upsert(self, vectors: Iterable[tuple[uuid.UUID, Sequence[float]]]) -> None:
        raise NotImplementedError

    def search(
        self,
        query_vector: Sequence[float],
        k: int,
        ids_filter: Set[uuid.UUID] | None = None,
    ) -> list[VectorSearchResult]:
        raise NotImplementedError


def create_vector_index(backend: str) -> VectorIndex:
    if backend == "numpy":
        return NumpyVectorIndex()
    if backend == "pgvector":
        return PgVectorIndex()
    raise ValueError(f"Unsupported VECTOR_BACKEND: {backend}")


@lru_cache
def get_shared_vector_index(backend: str) -> VectorIndex:
    """One process-local index, preloaded at startup and updated after catalog writes."""
    return create_vector_index(backend)
