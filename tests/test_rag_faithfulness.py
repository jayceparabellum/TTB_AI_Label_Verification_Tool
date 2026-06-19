"""Distinguishing-term faithfulness gate (Layer 3 — RAG).

A high-vocabulary-overlap OFF-corpus query can clear the coverage threshold by
sharing generic corpus terms ("alcohol", "label", "beverage") while its actual
SUBJECT term ("serving facts", "pictorial", "qr") is absent from the corpus. The
faithfulness gate refuses when the query's distinguishing (corpus-OOV) terms are
not addressed by the top retrieved chunk, so a topically adjacent chunk doesn't
get cited as if it answered the specific question.
"""

from rag import generate
from rag.retrieve import Retriever


# --- DF / distinguishing-term helper ----------------------------------------
def test_corpus_oov_terms_are_distinguishing():
    r = Retriever()
    # Subject terms absent from the labeling corpus.
    assert r.corpus_df("pictorial") == 0
    assert r.corpus_df("qr") == 0
    assert "pictorial" in r.distinguishing_terms("pictorial health warnings on labels")
    assert "qr" in r.distinguishing_terms("qr code requirements for alcohol labels")


def test_common_corpus_terms_are_not_distinguishing():
    r = Retriever()
    # Generic terms that appear across many chunks must NOT be flagged.
    assert r.corpus_df("alcohol") > 0
    assert r.corpus_df("label") > 0
    flagged = r.distinguishing_terms("alcohol label requirements")
    assert "alcohol" not in flagged and "label" not in flagged


def test_rarest_present_term_is_not_distinguishing():
    # Boundary: a term that appears in the corpus even once (df >= 1) is NOT OOV and
    # must not be flagged — locks the gate at df==0, so it can't drift to df<=1.
    r = Retriever()
    assert r.corpus_df("proof") >= 1
    assert "proof" not in r.distinguishing_terms("proof requirement for vodka")


def test_synonym_expansion_keys_are_excludable():
    # Expansion keys (matcher synonyms) can be corpus-OOV themselves but must be
    # excludable so they aren't mistaken for distinguishing subject terms.
    r = Retriever()
    excl = {"title", "case", "header"}
    flagged = r.distinguishing_terms("title case header", exclude=excl)
    assert flagged == set()


# --- Off-corpus high-overlap queries now REFUSE ------------------------------
def test_serving_facts_refused():
    assert generate.answer(
        "Are Serving Facts panels required on alcohol beverage labels?"
    )["status"] == "refused"


def test_pictorial_warnings_refused():
    assert generate.answer(
        "What pictorial health warnings are required on alcohol labels?"
    )["status"] == "refused"


def test_qr_code_refused():
    assert generate.answer(
        "What QR code requirements apply to alcohol labels?"
    )["status"] == "refused"


# --- In-corpus queries must still ANSWER (no regression) ---------------------
def test_in_corpus_queries_still_answer():
    cases = [
        ("what does a wine label need?", "wine"),
        ("what is the proof requirement for vodka", "spirits"),
        ("what does a malt beverage label need?", "malt"),
        ("age statement for whisky", "spirits"),
    ]
    for q, bt in cases:
        res = generate.answer(q, bt)
        assert res["status"] == "answered", f"{q!r} wrongly refused"
        assert res["citations"], f"{q!r} answered without citations"


def test_explain_flag_still_maps_to_16_22():
    # The failure-description vocabulary ("Title case", "ALL CAPS", "header") is
    # corpus-OOV but bridged by expansion to real regulatory terms; the gate must
    # NOT refuse it.
    res = generate.explain_flag("government_warning", "header is Title case not ALL CAPS")
    assert res["status"] == "answered"
    assert res["citations"][0]["section"] == "16.22"


def test_explain_flag_real_fields_answer_off_corpus_field_refuses():
    # explain_flag is agent-callable with arbitrary strings — the gate keys on the
    # FIELD (the real subject). Real flagged fields stay answered; an off-corpus
    # subject field is refused (closes the explain_flag bypass found in review).
    for field, reason in [("government_warning", "wording differs"),
                          ("alcohol_content", "label differs from application")]:
        assert generate.explain_flag(field, reason)["status"] == "answered", field
    assert generate.explain_flag(
        "serving_facts", "panel required on alcohol beverage label")["status"] == "refused"
