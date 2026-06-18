"""Grounded, cite-or-refuse answer assembly.

Answers ONLY from retrieved chunks and always attaches the controlling citation;
if retrieval is empty or below the confidence threshold it REFUSES with a fixed
message — never answering a regulatory question from model memory. The assembly is
extractive (quotes the regulation + cites it), which is deterministic and offline;
an optional local-LLM summarization pass can sit on top later without changing the
grounding contract.
"""

from __future__ import annotations

from agent import config
from .retrieve import Result, get_retriever

REFUSAL = "Not found in the regulations on file."

# Light query expansion for known regulatory-failure vocabulary, so BM25 (which is
# literal) bridges synonyms like "caps" -> "capital letters". This biases retrieval
# with REAL regulatory terms; the answer is still grounded + cited from the corpus.
_EXPAND = {
    "caps": "capital letters", "case": "capital letters bold", "title": "capital letters",
    "uppercase": "capital letters", "bold": "bold type", "header": "capital letters bold",
    "format": "legibility format", "legible": "legibility", "missing": "required statement",
    "wording": "exact statement", "abv": "alcohol content", "class": "class type designation",
}


def _expand(text: str) -> str:
    extra = [v for k, v in _EXPAND.items() if k in text.lower()]
    return text + (" " + " ".join(extra) if extra else "")


def _dense_supports(top) -> bool:
    """A strong cosine hit can support an answer when lexical coverage is thin —
    this is what lets the dense backend recover a genuine semantic match. No-op when
    dense is off (dense_sim is None), so the BM25-only contract is unchanged."""
    return getattr(top, "dense_sim", None) is not None and top.dense_sim >= config.RAG_DENSE_MIN_SIM


def _supported(top) -> bool:
    """Refuse a single incidental word-overlap: with a multi-term query we need at
    least two matched content terms, and coverage must clear the threshold. A strong
    dense (cosine) match is an alternative path to support."""
    if top is None:
        return False
    if top.matched == 0:
        return _dense_supports(top)
    if top.n_query_terms >= 3 and top.matched < 2:
        return _dense_supports(top)
    return top.coverage >= config.RAG_MIN_CONFIDENCE or _dense_supports(top)


def _cite(r: Result) -> dict:
    c = r.chunk
    return {"citation": c.citation, "section": c.section, "source_url": c.source_url,
            "beverage_type": c.beverage_type}


def _compose(results: list[Result]) -> str:
    parts = [f"{r.chunk.citation} — {r.chunk.text}" for r in results]
    return "Based only on the regulations on file:\n\n" + "\n\n".join(parts)


def answer(question: str, beverage_type: str | None = None, k: int = 4) -> dict:
    """Answer a regulatory question with citations, or refuse if unsupported."""
    results = get_retriever().retrieve(question, k=k)
    if beverage_type:
        bt = beverage_type.lower()
        scoped = [r for r in results if r.chunk.beverage_type in (bt, "all")]
        results = scoped or results
    top = results[0] if results else None
    if not _supported(top):
        return {"status": "refused", "answer": REFUSAL, "citations": []}
    # Keep chunks that genuinely support the question (decent coverage).
    floor = max(config.RAG_MIN_CONFIDENCE, top.coverage * 0.5)
    used = [r for r in results if r.coverage >= floor][:3] or [top]
    return {"status": "answered", "answer": _compose(used),
            "citations": [_cite(r) for r in used]}


def explain_flag(field: str, failure_reason: str) -> dict:
    """Attach the controlling regulation to a deterministic FLAG, with a citation."""
    query = _expand(f"{field.replace('_', ' ')} {failure_reason}")
    results = get_retriever().retrieve(query, k=3)
    top = results[0] if results else None
    if not _supported(top):
        return {"status": "refused", "explanation": REFUSAL, "citations": []}
    return {"status": "answered",
            "explanation": f"{top.chunk.citation} — {top.chunk.text}",
            "citations": [_cite(top)]}
