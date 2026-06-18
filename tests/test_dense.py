"""Dense retrieval backend — fusion + cite-or-refuse, proven offline with a
deterministic stub embedder (no model download). The real BGE-small run is a host
step; here we exercise the same DenseIndex + RRF + generate path with hashed
bag-of-words vectors, so cosine tracks lexical overlap and the wiring is real."""

import hashlib
import re

import numpy as np
import pytest

from agent import config
from rag import generate
from rag.dense import BGEEmbedder, DenseIndex, build_dense_backend
from rag.ingest import load_corpus
from rag.retrieve import Retriever


class StubEmbedder:
    """Deterministic hashed bag-of-words embedder: cosine ~ shared-word overlap.
    Stands in for BGE-small with zero network and stable vectors across runs."""

    dim = 96

    def encode(self, texts):
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for r, t in enumerate(texts):
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                h = int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim
                out[r, h] += 1.0
        return out


@pytest.fixture
def chunks():
    return load_corpus()


# --- DenseIndex: cosine search returns the on-topic chunk --------------------
def test_dense_index_ranks_relevant_chunk_first(chunks):
    idx = DenseIndex(chunks, StubEmbedder())
    hits = idx.search("alcohol content statement for wine", k=3)
    assert hits and all(0.0 <= sim <= 1.0001 for _, sim in hits)
    top_section = chunks[hits[0][0]].section
    assert top_section in {"4.36", "4.32"}          # the wine alcohol-content sections


# --- Retriever fusion: dense_sim is populated, lexical hits still surface -----
def test_retriever_fuses_dense_and_populates_similarity(chunks):
    r = Retriever(chunks=chunks, dense=DenseIndex(chunks, StubEmbedder()))
    results = r.retrieve("what does a wine label need?", k=4)
    assert any(res.dense_sim is not None for res in results)
    assert "4.32" in {res.chunk.section for res in results}   # controlling section retained


def test_bm25_only_leaves_dense_sim_none(chunks):
    r = Retriever(chunks=chunks, dense=None)
    results = r.retrieve("what does a wine label need?", k=4)
    assert all(res.dense_sim is None for res in results)


# --- build_dense_backend honors config.RAG_DENSE -----------------------------
def test_build_off_returns_none(monkeypatch, chunks):
    monkeypatch.setattr(config, "RAG_DENSE", "off")
    assert build_dense_backend(chunks, embedder=StubEmbedder()) is None


def test_build_auto_without_dep_is_bm25_only(monkeypatch, chunks):
    monkeypatch.setattr(config, "RAG_DENSE", "auto")
    monkeypatch.setattr(BGEEmbedder, "available", staticmethod(lambda: False))
    assert build_dense_backend(chunks) is None          # silently falls back


def test_build_on_without_dep_raises(monkeypatch, chunks):
    monkeypatch.setattr(config, "RAG_DENSE", "on")
    monkeypatch.setattr(BGEEmbedder, "available", staticmethod(lambda: False))
    with pytest.raises(RuntimeError):
        build_dense_backend(chunks)


def test_build_with_injected_embedder_is_enabled(monkeypatch, chunks):
    monkeypatch.setattr(config, "RAG_DENSE", "auto")     # pin: independent of ambient env
    backend = build_dense_backend(chunks, embedder=StubEmbedder())
    assert backend is not None and backend.available


# --- Contract holds with dense on: cite in-corpus, refuse out-of-corpus -------
def test_generate_with_dense_cites_and_refuses(monkeypatch, chunks):
    dense_retriever = Retriever(chunks=chunks, dense=DenseIndex(chunks, StubEmbedder()))
    monkeypatch.setattr(generate, "get_retriever", lambda: dense_retriever)

    # Exact section ordering under fusion depends on the embedder; the contract is
    # that it answers, scopes to wine, and cites — not a specific stub ranking.
    answered = generate.answer("what does a wine label need?", "wine")
    assert answered["status"] == "answered"
    secs = {c["section"] for c in answered["citations"]}
    assert secs and all(s.startswith("4.") for s in secs)

    refused = generate.answer("how do I bake sourdough bread")
    assert refused["status"] == "refused" and refused["citations"] == []
