"""Layer 3 — RAG: ingest metadata, term-heavy retrieval, and the cite-or-refuse
contract (cites in-corpus, refuses out-of-corpus, faithful to chunks)."""

import json
from pathlib import Path

from rag import generate
from rag.ingest import load_corpus
from rag.retrieve import Retriever

_VERIFIED = Path(__file__).resolve().parent.parent / "rag" / "corpus" / "ecfr_verified.json"


def test_every_chunk_cites_an_ecfr_verified_section():
    """Guard against the §5.66->§5.74 class of error: every corpus chunk must cite a
    section number that exists in the eCFR-verified snapshot, under the matching part.
    Offline (no network) — refresh the snapshot when the corpus gains sections."""
    verified = json.loads(_VERIFIED.read_text())["sections"]
    for c in load_corpus():
        assert c.section in verified, f"§{c.section} is not in the eCFR-verified snapshot"
        assert verified[c.section]["part"] == c.part, (
            f"§{c.section} is in part {verified[c.section]['part']}, not {c.part}")


def test_ingest_carries_citation_metadata():
    chunks = load_corpus()
    assert len(chunks) >= 12
    by_section = {c.section: c for c in chunks}
    assert "16.21" in by_section and "16.22" in by_section and "4.32" in by_section
    # Parts 5 (distilled spirits) and 7 (malt beverages) are in the corpus.
    assert "5.63" in by_section and "5.65" in by_section and "7.63" in by_section
    assert by_section["5.65"].beverage_type == "spirits"
    assert by_section["7.63"].beverage_type == "malt"
    # §16.21 is the verbatim official statement.
    assert by_section["16.21"].text.startswith("GOVERNMENT WARNING:")
    for c in chunks:
        assert c.citation.startswith("27 CFR") and c.source_url.startswith("https://")


def test_retrieval_finds_controlling_section_for_term_heavy_query():
    r = Retriever()
    top = r.retrieve("government warning capital letters bold", k=1)[0]
    assert top.chunk.section == "16.22"
    wine = {res.chunk.section for res in r.retrieve("wine label brand alcohol", k=3)}
    assert "4.32" in wine


def test_answer_in_corpus_is_cited():
    res = generate.answer("what does a wine label need?", "wine")
    assert res["status"] == "answered"
    sections = {c["section"] for c in res["citations"]}
    assert "4.32" in sections
    # Faithful: every cited chunk's text is present (extractive, no invented claims).
    by_section = {c.section: c for c in load_corpus()}
    for s in sections:
        assert by_section[s].text in res["answer"]


def test_answer_covers_spirits_and_malt():
    # Distilled-spirits proof labeling (Part 5) and malt-beverage labeling (Part 7)
    # are now in-corpus and cited.
    spirits = generate.answer("what is the proof requirement for vodka", "spirits")
    assert spirits["status"] == "answered"
    assert "5.65" in {c["section"] for c in spirits["citations"]}
    malt = generate.answer("what does a malt beverage label need?", "malt")
    assert malt["status"] == "answered"
    assert "7.63" in {c["section"] for c in malt["citations"]}


def test_answer_refuses_out_of_corpus():
    # Genuinely out-of-corpus: labeling corpus has no excise-tax or baking content.
    for q in ("what is the federal excise tax rate", "how do I bake bread?"):
        res = generate.answer(q)
        assert res["status"] == "refused"
        assert res["answer"] == generate.REFUSAL and res["citations"] == []


def test_answer_refuses_thin_overlap_out_of_corpus():
    # A thin-overlap off-corpus query (alcohol-labeling sub-topic absent from the
    # corpus) that the old 0.30 floor wrongly ANSWERED; the calibrated 0.50 coverage
    # gate now refuses it. Guards the threshold from drifting lenient again.
    # (High-vocab-overlap off-corpus queries like "Serving Facts panels" / "pictorial
    # warnings" are NOT caught by coverage alone — those are now caught by the
    # distinguishing-term faithfulness gate; see tests/test_rag_faithfulness.py.)
    assert generate.answer("What QR code requirements apply to alcohol labels?")["status"] == "refused"


def test_answer_still_cites_borderline_in_corpus():
    # The tightening must not refuse a genuine in-corpus question with thinner overlap.
    res = generate.answer("what is the proof requirement for vodka", "spirits")
    assert res["status"] == "answered" and res["citations"]


def test_explain_flag_caps_maps_to_16_22():
    res = generate.explain_flag("government_warning", "header is Title case not ALL CAPS")
    assert res["status"] == "answered"
    assert res["citations"][0]["section"] == "16.22"


def test_golden_eval_meets_thresholds():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "run_rag_eval", Path(__file__).resolve().parent.parent / "eval" / "run_rag_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    m = mod.evaluate()
    assert m["hit_rate"] >= 0.8
    assert m["faithfulness"] == 1.0
    assert m["citation_rate"] == 1.0
