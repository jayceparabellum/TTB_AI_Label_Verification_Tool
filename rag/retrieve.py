"""Retrieval over the CFR corpus.

Hybrid by design: BM25 keyword search (great for term-heavy regulatory queries —
section numbers, "750 mL", "type size") plus an optional dense vector backend.
The dense backend (BGE-small via sentence-transformers + Chroma) is host-deferred:
it slots in behind `DenseBackend` when the host is provisioned; until then
retrieval is BM25-only, which is fully offline and deterministic.

A per-result `coverage` (fraction of the query's content words found in the chunk)
gives an interpretable confidence the generator uses to decide cite-vs-refuse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from .ingest import Chunk, load_corpus

_STOP = {
    "the", "a", "an", "of", "to", "for", "and", "or", "is", "are", "what", "does",
    "do", "need", "needs", "on", "in", "must", "be", "my", "this", "that", "it",
    "how", "can", "i", "with", "as", "at", "by", "if", "show", "me", "tell", "about",
}


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9.]+", text.lower()) if t]


def _content(text: str) -> set[str]:
    return {t for t in _tokens(text) if t not in _STOP and len(t) > 1}


# --- Dense backend seam (host-deferred) --------------------------------------
class DenseBackend:
    """Interface for an optional dense retriever (BGE-small embeddings + Chroma).
    Enabled when the host is provisioned; see rag/store.py. Until then unused."""

    available = False

    def search(self, query: str, k: int):  # pragma: no cover - not wired yet
        raise NotImplementedError


@dataclass
class Result:
    chunk: Chunk
    score: float          # BM25 rank score
    coverage: float       # fraction of query content-terms present in the chunk
    matched: int          # count of query content-terms present in the chunk
    n_query_terms: int    # total query content-terms (for the refuse rule)


class Retriever:
    def __init__(self, chunks: list[Chunk] | None = None, dense: DenseBackend | None = None):
        self.chunks = chunks if chunks is not None else load_corpus()
        self._bm25 = BM25Okapi([_tokens(c.text + " " + c.heading) for c in self.chunks])
        self.dense = dense if (dense and dense.available) else None

    def retrieve(self, query: str, k: int = 4) -> list[Result]:
        scores = self._bm25.get_scores(_tokens(query))
        q_terms = _content(query)
        ranked = sorted(range(len(self.chunks)), key=lambda i: scores[i], reverse=True)[:k]
        out = []
        for i in ranked:
            chunk_terms = _content(self.chunks[i].text + " " + self.chunks[i].heading)
            matched = len(q_terms & chunk_terms)
            cov = (matched / len(q_terms)) if q_terms else 0.0
            out.append(Result(chunk=self.chunks[i], score=float(scores[i]), coverage=cov,
                              matched=matched, n_query_terms=len(q_terms)))
        # NOTE: when self.dense is enabled, fuse dense ranks here (RRF) before return.
        return out


# Process-wide retriever (corpus is small + static).
_RETRIEVER: Retriever | None = None


def get_retriever() -> Retriever:
    global _RETRIEVER
    if _RETRIEVER is None:
        _RETRIEVER = Retriever()
    return _RETRIEVER
