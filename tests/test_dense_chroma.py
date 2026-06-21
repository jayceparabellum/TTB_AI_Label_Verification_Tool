"""Chroma persistence backend (PRD-driven, opt-in RAG_DENSE_STORE=chroma).

Proves the persistent store with a deterministic stub embedder (no model download):
search works, a restart reuses the persisted vectors instead of re-embedding, a
corpus/embedder change rebuilds, and the whole path stays offline. chromadb is an
optional dependency, so the module skips where it isn't installed (e.g. CI).
"""

import dataclasses
import hashlib
import re
import socket

import numpy as np
import pytest

pytest.importorskip("chromadb")          # optional dep — skip the suite if absent

from agent import config
from rag.dense import ChromaDenseBackend, DenseIndex, build_dense_backend
from rag.ingest import load_corpus


class CountingStub:
    """Hashed bag-of-words embedder that records how many texts it encoded — so a
    test can prove a restart did NOT re-embed the corpus."""

    dim = 96

    def __init__(self):
        self.encoded = 0

    def encode(self, texts):
        self.encoded += len(texts)
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for r, t in enumerate(texts):
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                out[r, int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1.0
        return out


@pytest.fixture
def chunks():
    return load_corpus()


@pytest.fixture(autouse=True)
def _chroma_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(config, "RAG_DENSE_STORE", "chroma")


def test_chroma_search_ranks_relevant_chunk(chunks):
    backend = ChromaDenseBackend(chunks, CountingStub())
    hits = backend.search("alcohol content statement for wine", k=3)
    assert hits and all(0.0 <= sim <= 1.0001 for _, sim in hits)
    assert chunks[hits[0][0]].section in {"4.36", "4.32"}     # wine alcohol-content


def test_restart_reuses_persisted_vectors_without_reembedding(chunks):
    first = CountingStub()
    ChromaDenseBackend(chunks, first)
    assert first.encoded == len(chunks)            # embedded the whole corpus once

    second = CountingStub()
    backend2 = ChromaDenseBackend(chunks, second)  # same dir, same corpus + embedder
    assert second.encoded == 0                     # reused from disk — no re-embed
    # and it still answers (the query embed is the only encode it does)
    hits = backend2.search("wine alcohol content", k=3)
    assert hits and second.encoded == 1


def test_changed_corpus_triggers_rebuild(chunks):
    ChromaDenseBackend(chunks, CountingStub())     # persist for the full corpus
    edited = [dataclasses.replace(chunks[0], text=chunks[0].text + " EDITED"), *chunks[1:]]
    stub = CountingStub()
    ChromaDenseBackend(edited, stub)               # same count, different fingerprint
    assert stub.encoded == len(edited)             # rebuilt rather than served stale


def test_parity_with_in_memory_index(chunks):
    query = "government health warning statement"
    chroma_top = ChromaDenseBackend(chunks, CountingStub()).search(query, k=1)[0][0]
    memory_top = DenseIndex(chunks, CountingStub()).search(query, k=1)[0][0]
    assert chroma_top == memory_top


def test_build_dense_backend_routes_to_chroma(chunks, monkeypatch):
    monkeypatch.setattr(config, "RAG_DENSE", "auto")     # conftest pins "off" for hermeticity
    backend = build_dense_backend(chunks, embedder=CountingStub())
    assert isinstance(backend, ChromaDenseBackend)


def test_build_raises_when_chroma_requested_without_dep(chunks, monkeypatch):
    import rag.dense as dense
    monkeypatch.setattr(config, "RAG_DENSE", "auto")
    monkeypatch.setattr(dense.importlib.util, "find_spec",
                        lambda name: None if name == "chromadb" else True)
    with pytest.raises(RuntimeError, match="chromadb is not installed"):
        build_dense_backend(chunks, embedder=CountingStub())


def test_chroma_backend_runs_offline(chunks, monkeypatch):
    real_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise OSError(f"offline test: outbound connection to {host!r} blocked")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    backend = ChromaDenseBackend(chunks, CountingStub())      # build + persist
    assert backend.search("wine", k=2)                        # query — all local
