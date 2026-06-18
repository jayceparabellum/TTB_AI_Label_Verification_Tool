"""Phase 5 — the verify_label tool attaches the controlling regulation (with a
citation) to any FLAGGED field, grounded in the RAG corpus. Invariants under test:

- The annotation is ADVISORY: it never changes the deterministic pass/fail verdict.
- It lands ONLY on flagged fields, never on a passing field.
- The deterministic core path (run_verify) stays RAG-free, so RAG can never block
  the < 5 s verify SLA.
- A RAG failure during enrichment degrades gracefully — the verdict still returns.
"""

from pathlib import Path

import pytest

from agent import tools as T
from agent.images import STORE
from rag import generate

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(), reason="sample images not generated")


@pytest.fixture(autouse=True)
def _seed_store():
    STORE._images.clear()
    STORE.seed_samples()
    yield
    STORE._images.clear()


def _invoke(image_id, brand="Stone's Throw", abv="5.0"):
    return T.verify_label.invoke(
        {"brand": brand, "alcohol_content": abv,
         "state": {"active_image_id": image_id}})


def _field(result, name):
    return next(f for f in result["fields"] if f["field"] == name)


# --- Happy path: a FLAG carries its controlling regulation --------------------
def test_warning_flag_attaches_controlling_regulation():
    out = _invoke("bad_warning")                      # Title-case header -> FLAG
    warn = _field(out, "government_warning")
    assert warn["passed"] is False
    reg = warn["regulation"]
    assert reg["section"] == "16.22" and reg["citation"]
    assert reg["explanation"]


def test_abv_flag_attaches_controlling_regulation():
    out = _invoke("abv_mismatch")                     # ABV mismatch -> FLAG
    abv = _field(out, "alcohol_content")
    assert abv["passed"] is False
    assert abv.get("regulation") and abv["regulation"]["citation"]


# --- Advisory only: verdict is untouched, passing fields stay bare ------------
def test_passing_fields_get_no_regulation():
    out = _invoke("clean_pass")
    assert out["overall_pass"] is True
    assert all("regulation" not in f for f in out["fields"])


def test_enrichment_does_not_change_the_verdict():
    enriched = _invoke("abv_mismatch")
    bare = T.run_verify("abv_mismatch", "Stone's Throw", "5.0")
    assert {f["field"]: f["passed"] for f in enriched["fields"]} == \
           {f["field"]: f["passed"] for f in bare["fields"]}
    assert enriched["overall_pass"] == bare["overall_pass"]


# --- RAG stays OFF the deterministic < 5 s core path -------------------------
def test_run_verify_is_rag_free():
    """The deterministic verdict carries no regulation annotation — RAG enrichment
    lives only in the tool wrapper, never on the measured core path."""
    bare = T.run_verify("bad_warning", "Stone's Throw", "5.0")
    assert all("regulation" not in f for f in bare["fields"])
    assert bare["elapsed_ms"] < 5000


def test_enrichment_failure_degrades_gracefully(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("retriever unavailable")
    monkeypatch.setattr(generate, "explain_flag", boom)
    out = _invoke("bad_warning")                      # must not raise
    warn = _field(out, "government_warning")
    assert warn["passed"] is False                    # verdict intact
    assert warn.get("regulation") is None             # annotation simply absent
