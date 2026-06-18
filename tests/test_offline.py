"""Offline proof: with outbound network blocked, the deterministic verification
path and the RAG knowledge layer still work — proving no cloud dependency
(OCR is local Tesseract, matching is local, retrieval is local BM25 over a
committed corpus). The model path is local-only (Ollama on loopback) and out of
scope here; this asserts nothing leaves the network."""

import socket
from pathlib import Path

import pytest

from app.verify import verify_label
from rag import generate

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(), reason="sample images not generated")

_LOOPBACK = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


@pytest.fixture
def no_outbound(monkeypatch):
    """Block any socket connection to a non-loopback address."""
    real_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in _LOOPBACK:
            raise OSError(f"offline test: outbound connection to {host!r} blocked")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield


def test_verification_runs_fully_offline(no_outbound):
    r = verify_label((SAMPLES / "clean_pass.png").read_bytes(),
                     brand="Stone's Throw", alcohol_content="5.0")
    assert r.readable and r.overall_pass          # OCR + matching, no cloud


def test_rag_runs_fully_offline(no_outbound):
    answered = generate.answer("what does a wine label need?", "wine")
    assert answered["status"] == "answered" and answered["citations"]
    assert generate.answer("vodka proof requirement")["status"] == "refused"
    flag = generate.explain_flag("government_warning", "Title case not ALL CAPS")
    assert flag["citations"][0]["section"] == "16.22"
