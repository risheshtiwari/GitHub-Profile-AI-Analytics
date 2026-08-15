"""Repo Chat — Stage 3: embeddings.

Same adapter pattern as `ai_engine.py`: the rest of the code depends on the
`Embedder` protocol, not on OpenAI, so the provider can be swapped.

Two implementations ship:

* `OpenAIEmbedder` — text-embedding-3-small with dimension truncation (512 by
  default). Truncating cuts storage ~3x with negligible retrieval loss, which
  matters because vectors live in a JSON column rather than pgvector.
* `HashingEmbedder` — a deterministic hashed bag-of-tokens vector requiring no
  API key. Retrieval still works (lexical overlap dominates code search), so
  tests and offline demos run for free. Selected automatically when no
  `OPENAI_API_KEY` is configured.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from typing import Protocol

from app.core.config import get_settings

settings = get_settings()

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


class Embedder(Protocol):
    name: str
    dimensions: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


def _l2_normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def tokenize(text: str) -> list[str]:
    """Identifier-aware tokenizer: splits snake_case and camelCase so a query
    for 'developer score' matches `composite_developer_score`."""
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        lowered = raw.lower()
        tokens.append(lowered)
        parts = [part for part in raw.split("_") if part]
        for part in parts:
            camel = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", part)
            for piece in camel:
                piece_lower = piece.lower()
                if piece_lower != lowered and len(piece_lower) > 2:
                    tokens.append(piece_lower)
    return tokens


class HashingEmbedder:
    """Deterministic, dependency-free fallback. Not as good as a learned model,
    but stable, free, and enough for lexical-ish retrieval over code."""

    name = "hashing-fallback"

    def __init__(self, dimensions: int | None = None):
        self.dimensions = dimensions or settings.embedding_dimensions

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = tokenize(text)
        for token in tokens:
            digest = hashlib.md5(token.encode()).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        return _l2_normalise(vector)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class OpenAIEmbedder:
    name = "openai"

    def __init__(self, model: str | None = None, dimensions: int | None = None):
        from openai import AsyncOpenAI

        self.model = model or settings.embedding_model
        self.dimensions = dimensions or settings.embedding_dimensions
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(
            model=self.model,
            input=batch,
            dimensions=self.dimensions,
        )
        # The API preserves input order, but sort by index to be explicit.
        ordered = sorted(response.data, key=lambda item: item.index)
        return [_l2_normalise(list(item.embedding)) for item in ordered]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        size = settings.embedding_batch_size
        batches = [texts[i:i + size] for i in range(0, len(texts), size)]
        # Bounded concurrency — fast, without tripping embedding rate limits.
        semaphore = asyncio.Semaphore(4)

        async def run(batch: list[str]) -> list[list[float]]:
            async with semaphore:
                return await self._embed_batch(batch)

        results = await asyncio.gather(*(run(batch) for batch in batches))
        return [vector for batch_result in results for vector in batch_result]

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._embed_batch([text])
        return vectors[0]


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    """Falls back to the hashing embedder when no OpenAI key is configured, so
    the feature degrades instead of erroring out."""
    global _embedder
    if _embedder is None:
        if settings.openai_api_key:
            _embedder = OpenAIEmbedder()
        else:
            _embedder = HashingEmbedder()
    return _embedder


def set_embedder(embedder: Embedder | None) -> None:
    """Test seam — inject a fake embedder (or reset with None)."""
    global _embedder
    _embedder = embedder
