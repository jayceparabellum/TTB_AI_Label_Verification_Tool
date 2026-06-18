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


def _fold(t: str) -> str:
    """Fold a trailing plural 's' so 'labels' matches 'label' and 'spirits' matches
    'spirit'. Applied symmetrically to the index and the query, so it only ever
    improves recall — never introduces an asymmetric mismatch. Conservative: skips
    short tokens and 'ss' words (class, address)."""
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _raw_tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9.]+", text.lower()) if t]


def _tokens(text: str) -> list[str]:
    return [_fold(t) for t in _raw_tokens(text)]


def _content(text: str) -> set[str]:
    # Drop stopwords on the RAW token (so 'does' is removed, not folded to 'doe'),
    # then fold the survivors for symmetric matching against the index.
    return {_fold(t) for t in _raw_tokens(text) if t not in _STOP and len(t) > 1}


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
        # Weight the heading: it's a high-signal summary of the section ("Mandatory
        # label information for wine"), and weighting it counteracts BM25 length
        # normalization penalizing the longest, most comprehensive sections.
        self._bm25 = BM25Okapi(
            [_tokens(c.text + " " + (c.heading + " ") * 3) for c in self.chunks])
        self.dense = dense if (dense and dense.available) else None

    def retrieve(self, query: str, k: int = 4) -> list[Result]:
        scores = self._bm25.get_scores(_tokens(query))
        q_terms = _content(query)
        # Rank by distinct query-term coverage first, BM25 as the tiebreak. For
        # short regulatory queries the count of distinct terms matched is a stronger
        # relevance signal than raw BM25, which can rank a chunk matching ONE common
        # term (e.g. "wine") above the controlling section matching BOTH terms but
        # penalized for length. BM25 still orders chunks with equal coverage.
        matched_by_i = [
            len(q_terms & _content(c.text + " " + c.heading)) for c in self.chunks]
        ranked = sorted(range(len(self.chunks)),
                        key=lambda i: (matched_by_i[i], scores[i]), reverse=True)[:k]
        out = []
        for i in ranked:
            matched = matched_by_i[i]
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
