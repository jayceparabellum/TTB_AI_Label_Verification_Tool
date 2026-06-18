"""Hermetic retrieval for the test suite.

`get_retriever()` auto-enables the dense backend when sentence-transformers is
importable (config.RAG_DENSE="auto"), and caches a process-wide singleton. Left
ambient, the contract tests would run dense-on on a dev box that happens to have
the dep installed but BM25-only in CI/Render — the two regimes could silently
diverge, and the singleton would leak the first regime across tests.

This autouse fixture pins every test to BM25-only (the CI/Render regime) and
resets the singleton around each test, so the default suite is deterministic
regardless of host install state. Dense-specific tests opt in explicitly with an
injected stub embedder (see tests/test_dense.py).
"""

import pytest

import rag.retrieve as _retrieve
from agent import config


@pytest.fixture(autouse=True)
def _hermetic_retrieval(monkeypatch):
    monkeypatch.setattr(config, "RAG_DENSE", "off", raising=False)
    _retrieve._RETRIEVER = None          # rebuild under the pin; no cross-test leakage
    yield
    _retrieve._RETRIEVER = None
