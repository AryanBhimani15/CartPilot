from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol

from app.config import Settings

TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")
DETERMINISTIC_MODEL = "deterministic-hash-v1"


class EmbeddingProvider(Protocol):
    """Provider boundary for real demo embeddings and hermetic test embeddings."""

    model: str

    async def embed_documents(self, documents: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, query: str) -> list[float]: ...


def _tokens(text: str) -> list[str]:
    normalised = text.lower().replace("5 km", "5km").replace("flat feet", "flat_feet")
    tokens = TOKEN_PATTERN.findall(normalised)
    # The deterministic provider is deliberately a modest semantic floor: it maps common
    # shopper phrasing to the catalog's structured vocabulary without relying on a network.
    if "flat_feet" in tokens:
        tokens.extend(("stability", "motion_control"))
    if "daily" in tokens or "5km" in tokens:
        tokens.append("daily_easy_runs")
    if "watch" in tokens:
        tokens.append("gps_watches")
    if "run" in tokens or "running" in tokens or "runs" in tokens:
        tokens.append("running_shoes")
    return tokens


class DeterministicEmbeddingProvider:
    """A seeded hashing projection that is stable across machines and test runs."""

    model = DETERMINISTIC_MODEL

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.dimensions = dimensions

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        terms = _tokens(text)
        for index, term in enumerate(terms):
            features = (term, f"{terms[index - 1]}:{term}" if index else term)
            for feature in features:
                digest = hashlib.sha256(feature.encode("utf-8")).digest()
                bucket = int.from_bytes(digest[:4], "big") % self.dimensions
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        return vector if norm == 0 else [value / norm for value in vector]

    async def embed_documents(self, documents: Sequence[str]) -> list[list[float]]:
        return [self._embed(document) for document in documents]

    async def embed_query(self, query: str) -> list[float]:
        return self._embed(query)


class OpenAIEmbeddingProvider:
    """Hosted provider used by the demo when EMBEDDING_PROVIDER=openai.

    `text-embedding-3-small` is the documented model configured by default. The client is
    created lazily so deterministic tests never import or initialise an API client.
    """

    def __init__(self, model: str, api_key: str) -> None:
        if not api_key:
            raise ValueError("EMBEDDING_API_KEY is required when EMBEDDING_PROVIDER=openai")
        self.model = model
        self._api_key = api_key

    async def embed_documents(self, documents: Sequence[str]) -> list[list[float]]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._api_key)
        try:
            response = await client.embeddings.create(model=self.model, input=list(documents))
            return [list(item.embedding) for item in response.data]
        finally:
            await client.close()

    async def embed_query(self, query: str) -> list[float]:
        embeddings = await self.embed_documents([query])
        return embeddings[0]


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Build the configured provider, keeping pytest and eval deterministic by default."""
    if settings.app_env == "test" or settings.embedding_provider == "deterministic":
        return DeterministicEmbeddingProvider()
    if settings.embedding_provider == "openai":
        return OpenAIEmbeddingProvider(settings.embedding_model, settings.embedding_api_key or "")
    raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {settings.embedding_provider}")
