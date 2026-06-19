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
from collections import Counter
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from .ingest import Chunk, load_corpus

_STOP = {
    "the", "a", "an", "of", "to", "for", "and", "or", "is", "are", "what", "does",
    "do", "need", "needs", "on", "in", "must", "be", "my", "this", "that", "it",
    "how", "can", "i", "with", "as", "at", "by", "if", "show", "me", "tell", "about",
    # Generic interrogatives and bleached verbs carry no regulatory topical signal.
    # Dropping them keeps coverage honest and, crucially, keeps the distinguishing-
    # term gate from flagging a lone common verb (e.g. "put", "apply") as if it
    # were an off-corpus subject term.
    "who", "where", "when", "which", "put", "apply", "use", "used", "have", "has",
    "make", "made", "get", "take", "should", "may", "will", "would", "there",
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


# --- Dense backend seam -------------------------------------------------------
class DenseBackend:
    """Interface a dense retriever satisfies: an `available` flag and
    `search(query, k) -> [(chunk_index, cosine), ...]`. The concrete BGE-small +
    cosine-index implementation lives in rag/dense.py (DenseIndex); it duck-types
    this contract, so importing it here would only add a cycle. Off by default;
    enabled via config.RAG_DENSE when sentence-transformers is installed."""

    available = False

    def search(self, query: str, k: int):  # pragma: no cover - base stub
        raise NotImplementedError


@dataclass
class Result:
    chunk: Chunk
    score: float                  # BM25 rank score
    coverage: float               # fraction of query content-terms present in the chunk
    matched: int                  # count of query content-terms present in the chunk
    n_query_terms: int            # total query content-terms (for the refuse rule)
    dense_sim: float | None = None  # cosine similarity when the dense backend is on


_RRF_C = 60  # reciprocal-rank-fusion constant (standard); dampens top-rank dominance


class Retriever:
    def __init__(self, chunks: list[Chunk] | None = None, dense: DenseBackend | None = None):
        self.chunks = chunks if chunks is not None else load_corpus()
        # Weight the heading: it's a high-signal summary of the section ("Mandatory
        # label information for wine"), and weighting it counteracts BM25 length
        # normalization penalizing the longest, most comprehensive sections.
        self._bm25 = BM25Okapi(
            [_tokens(c.text + " " + (c.heading + " ") * 3) for c in self.chunks])
        self.dense = dense if (dense and getattr(dense, "available", False)) else None
        # Per-term corpus document frequency, computed once over the same content
        # tokens the matcher uses (so DF and `matched`/coverage stay consistent).
        # The corpus is small + static, so this is cheap and memoized for the
        # lifetime of the retriever.
        self._df: Counter = Counter()
        for c in self.chunks:
            for term in _content(c.text + " " + c.heading):
                self._df[term] += 1

    def corpus_df(self, term: str) -> int:
        """Document frequency of a content term across the corpus (0 = corpus-OOV)."""
        return self._df.get(_fold(term), 0)

    def distinguishing_terms(self, query: str, *, max_df: int = 0,
                             exclude: set[str] | None = None) -> set[str]:
        """The query's most-distinguishing content terms: those rare/absent in the
        corpus (DF <= max_df). DF == 0 (corpus-OOV) is the strongest signal the
        query is about something the corpus does not cover. `exclude` drops terms
        the matcher deliberately bridges via synonym expansion (which would
        otherwise look OOV), so synonyms aren't falsely flagged as distinguishing."""
        excl = {_fold(t) for t in (exclude or set())}
        return {t for t in _content(query)
                if self._df.get(t, 0) <= max_df and t not in excl}

    def chunk_content_terms(self, chunk: Chunk) -> set[str]:
        """Content terms present in a chunk, normalized the same way the query is."""
        return _content(chunk.text + " " + chunk.heading)

    def _lexical_order(self, matched_by_i: list[int], scores) -> list[int]:
        # Rank by distinct query-term coverage first, BM25 as the tiebreak. For
        # short regulatory queries the count of distinct terms matched is a stronger
        # relevance signal than raw BM25, which can rank a chunk matching ONE common
        # term (e.g. "wine") above the controlling section matching BOTH terms but
        # penalized for length. BM25 still orders chunks with equal coverage.
        return sorted(range(len(self.chunks)),
                      key=lambda i: (matched_by_i[i], scores[i]), reverse=True)

    def retrieve(self, query: str, k: int = 4) -> list[Result]:
        scores = self._bm25.get_scores(_tokens(query))
        q_terms = _content(query)
        n = len(self.chunks)
        matched_by_i = [
            len(q_terms & _content(c.text + " " + c.heading)) for c in self.chunks]
        lex_order = self._lexical_order(matched_by_i, scores)

        dense_sims: dict[int, float] = {}
        if self.dense is not None:
            # Fuse lexical + dense rankings with RRF: a chunk ranked high by EITHER
            # retriever floats up, so dense recovers semantic matches BM25 misses
            # without overturning strong lexical hits. Lexical coverage still gates
            # cite-vs-refuse downstream, so fusion reorders but never invents support.
            dense_sims = dict(self.dense.search(query, k=n))
            dense_order = sorted(range(n), key=lambda i: dense_sims.get(i, 0.0), reverse=True)
            lex_rank = {idx: r for r, idx in enumerate(lex_order)}
            den_rank = {idx: r for r, idx in enumerate(dense_order)}
            fused = {i: 1.0 / (_RRF_C + lex_rank[i]) + 1.0 / (_RRF_C + den_rank[i])
                     for i in range(n)}
            ranked = sorted(range(n), key=lambda i: fused[i], reverse=True)[:k]
        else:
            ranked = lex_order[:k]

        out = []
        for i in ranked:
            matched = matched_by_i[i]
            cov = (matched / len(q_terms)) if q_terms else 0.0
            out.append(Result(chunk=self.chunks[i], score=float(scores[i]), coverage=cov,
                              matched=matched, n_query_terms=len(q_terms),
                              dense_sim=dense_sims.get(i)))
        return out


# Process-wide retriever (corpus is small + static).
_RETRIEVER: Retriever | None = None


def get_retriever() -> Retriever:
    global _RETRIEVER
    if _RETRIEVER is None:
        # Build one chunk list and share it with both backends so indices align.
        from .dense import build_dense_backend
        chunks = load_corpus()
        _RETRIEVER = Retriever(chunks=chunks, dense=build_dense_backend(chunks))
    return _RETRIEVER
