"""U1 — recognized class/type designations dataset: schema integrity + the same
eCFR-verified-section guard the corpus uses, so a wrong/nonexistent citation fails
loudly and offline (the §5.66->§5.74 class of error)."""

import json
from pathlib import Path

from app.matching import normalize_loose

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "rag" / "corpus" / "class_type_designations.json"
_VERIFIED = _ROOT / "rag" / "corpus" / "ecfr_verified.json"


def _entries():
    return json.loads(_DATA.read_text())["designations"]


def test_dataset_parses_and_covers_both_beverage_types():
    entries = _entries()
    assert entries, "dataset is empty"
    kinds = {e["beverage_type"] for e in entries}
    assert kinds == {"wine", "spirits"}, kinds


def test_every_entry_has_required_provenance_fields():
    for e in _entries():
        assert e.get("designation", "").strip(), e
        assert e["beverage_type"] in {"wine", "spirits"}, e
        assert e.get("section"), e
        assert e.get("part"), e
        assert e.get("source_url", "").startswith("https://"), e
        assert isinstance(e.get("aliases", []), list), e


def test_designations_unique_within_beverage_type():
    seen = set()
    for e in _entries():
        key = (e["beverage_type"], normalize_loose(e["designation"]))
        assert key not in seen, f"duplicate designation {key}"
        seen.add(key)


def test_every_cited_section_is_ecfr_verified():
    # Same guard as tests/test_rag.py for the corpus: every cited section must exist in
    # the eCFR-verified snapshot under the matching part.
    verified = json.loads(_VERIFIED.read_text())["sections"]
    for e in _entries():
        sec = e["section"]
        assert sec in verified, f"§{sec} not in the eCFR-verified snapshot"
        assert verified[sec]["part"] == e["part"], (
            f"§{sec} is part {verified[sec]['part']}, not {e['part']}")


def test_optional_abv_envelopes_are_well_formed_and_cited():
    # The compositional ABV envelope is OPTIONAL; where present it must be a sane,
    # eCFR-verified bound (no fabricated numbers, no inverted ranges).
    verified = json.loads(_VERIFIED.read_text())["sections"]
    found_any = False
    for e in _entries():
        lo, hi = e.get("abv_min"), e.get("abv_max")
        if lo is None and hi is None:
            assert "composition_section" not in e, e  # no orphan comp section
            continue
        found_any = True
        for v in (lo, hi):
            if v is not None:
                assert isinstance(v, (int, float)) and 0 < v <= 100, e
        if lo is not None and hi is not None:
            assert lo <= hi, f"inverted ABV envelope {e}"
        comp_sec = e.get("composition_section", e["section"])
        assert comp_sec in verified, f"composition §{comp_sec} not eCFR-verified ({e})"
    assert found_any, "expected at least one entry to carry an ABV envelope"
