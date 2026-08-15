"""Repo Chat — Stage 4: retrieval.

Hybrid search over a repository's chunks:

    final_score = w * cosine(query, chunk) + (1 - w) * bm25(query, chunk)

Pure vector search is weak on code, because exact identifiers matter: a question
about `composite_developer_score` should hit the function with that literal name,
which BM25 nails and embeddings only approximate. Pure lexical search is weak on
intent ("how does it handle rate limiting?"). Combining the two is measurably
better than either alone on code corpora.

Top candidates are then re-ranked with **MMR** (Maximal Marginal Relevance) so
the LLM sees several *different* parts of the codebase rather than five near-
identical overlapping windows of the same file.

Everything is pure Python (numpy used only if already installed) so it needs no
extra infrastructure — no pgvector, no external vector DB.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from app.services.embeddings import tokenize

try:  # optional acceleration
    import numpy as _np
except ImportError:  # pragma: no cover - numpy is not a hard requirement
    _np = None


@dataclass
class ScoredChunk:
    index: int
    score: float
    vector_score: float
    lexical_score: float


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def cosine_scores(query: list[float], matrix: list[list[float]]) -> list[float]:
    """Query vs every chunk. Vectors are stored L2-normalised, so this is a dot
    product; the explicit cosine keeps it correct even if that ever changes."""
    if not matrix:
        return []
    if _np is not None:
        try:
            m = _np.asarray(matrix, dtype=_np.float32)
            q = _np.asarray(query, dtype=_np.float32)
            norms = _np.linalg.norm(m, axis=1) * (_np.linalg.norm(q) or 1.0)
            norms[norms == 0] = 1.0
            return (m @ q / norms).tolist()
        except (ValueError, TypeError):
            pass  # ragged/invalid input — fall through to pure Python
    return [cosine_similarity(query, row) for row in matrix]


class BM25Index:
    """Small Okapi BM25 over chunk token streams."""

    def __init__(self, documents: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_count = len(documents)
        self.doc_lengths = [len(doc) for doc in documents]
        self.avg_length = (sum(self.doc_lengths) / self.doc_count) if self.doc_count else 0.0
        self.term_freqs: list[Counter] = [Counter(doc) for doc in documents]

        doc_freq: Counter = Counter()
        for doc in documents:
            for term in set(doc):
                doc_freq[term] += 1
        self.idf = {
            term: math.log(1 + (self.doc_count - freq + 0.5) / (freq + 0.5))
            for term, freq in doc_freq.items()
        }

    def scores(self, query_tokens: list[str]) -> list[float]:
        results = [0.0] * self.doc_count
        if not self.doc_count or self.avg_length == 0:
            return results
        for index, freqs in enumerate(self.term_freqs):
            length = self.doc_lengths[index] or 1
            total = 0.0
            for term in query_tokens:
                frequency = freqs.get(term)
                if not frequency:
                    continue
                idf = self.idf.get(term, 0.0)
                numerator = frequency * (self.k1 + 1)
                denominator = frequency + self.k1 * (1 - self.b + self.b * length / self.avg_length)
                total += idf * numerator / denominator
            results[index] = total
        return results


def _min_max_normalise(values: list[float]) -> list[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    if high - low < 1e-12:
        return [0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def hybrid_scores(
    query_vector: list[float],
    query_text: str,
    matrix: list[list[float]],
    token_docs: list[list[str]],
    vector_weight: float = 0.7,
) -> list[ScoredChunk]:
    """Normalises both signals to [0,1] before blending — BM25 is unbounded and
    would otherwise swamp cosine similarity."""
    vector_raw = cosine_scores(query_vector, matrix)
    lexical_raw = BM25Index(token_docs).scores(tokenize(query_text))

    vector_norm = _min_max_normalise(vector_raw)
    lexical_norm = _min_max_normalise(lexical_raw)

    scored: list[ScoredChunk] = []
    for index in range(len(token_docs)):
        vector_score = vector_norm[index] if index < len(vector_norm) else 0.0
        lexical_score = lexical_norm[index] if index < len(lexical_norm) else 0.0
        combined = vector_weight * vector_score + (1 - vector_weight) * lexical_score
        scored.append(
            ScoredChunk(
                index=index,
                score=combined,
                vector_score=vector_raw[index] if index < len(vector_raw) else 0.0,
                lexical_score=lexical_raw[index] if index < len(lexical_raw) else 0.0,
            )
        )
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


def mmr_rerank(
    candidates: list[ScoredChunk],
    matrix: list[list[float]],
    top_k: int,
    diversity: float = 0.3,
) -> list[ScoredChunk]:
    """Maximal Marginal Relevance: greedily pick the candidate maximising
    `(1-d) * relevance - d * max_similarity_to_already_selected`."""
    if top_k <= 0 or not candidates:
        return []

    selected: list[ScoredChunk] = [candidates[0]]
    pool = candidates[1:]

    while len(selected) < top_k and pool:
        best_item = None
        best_value = -float("inf")
        for candidate in pool:
            redundancy = 0.0
            if candidate.index < len(matrix):
                for chosen in selected:
                    if chosen.index < len(matrix):
                        redundancy = max(
                            redundancy,
                            cosine_similarity(matrix[candidate.index], matrix[chosen.index]),
                        )
            value = (1 - diversity) * candidate.score - diversity * redundancy
            if value > best_value:
                best_value, best_item = value, candidate
        if best_item is None:
            break
        selected.append(best_item)
        pool.remove(best_item)

    return selected


def search(
    query_vector: list[float],
    query_text: str,
    matrix: list[list[float]],
    token_docs: list[list[str]],
    top_k: int = 8,
    candidate_k: int = 30,
    vector_weight: float = 0.7,
    diversity: float = 0.3,
) -> list[ScoredChunk]:
    """Hybrid retrieve -> MMR re-rank. Returns at most `top_k` chunk indices."""
    ranked = hybrid_scores(query_vector, query_text, matrix, token_docs, vector_weight)
    return mmr_rerank(ranked[:candidate_k], matrix, top_k, diversity)
