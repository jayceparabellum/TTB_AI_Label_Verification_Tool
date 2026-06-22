"""T7 — deterministic per-flag reason explanations (app/reasons.py)."""

from app.models import FieldResult
from app.reasons import explain


def _fr(field, passed, inconclusive=False, detail="similarity 80/100", review_kind=""):
    return FieldResult(field=field, label=field, passed=passed, expected="x",
                       found="y", detail=detail, inconclusive=inconclusive,
                       review_kind=review_kind)


def test_passing_field_has_no_reason():
    assert explain(_fr("brand", passed=True)) is None


def test_brand_flag_explains_and_cites():
    r = explain(_fr("brand", passed=False))
    assert r["status"] == "FLAG"
    assert "brand" in r["reason"].lower()
    assert "§4.33" in r["citation"]
    assert "similarity 80/100" in r["what_to_check"]      # matcher detail folded in


def test_alcohol_flag_explains_numeric_comparison():
    r = explain(_fr("alcohol_content", passed=False, detail="label says 7.5%"))
    assert r["status"] == "FLAG"
    assert "proof" in r["reason"].lower() or "number" in r["reason"].lower()
    assert "§4.36" in r["citation"]


def test_warning_review_defers_with_16_21_citation():
    r = explain(_fr("government_warning", passed=False, inconclusive=True))
    assert r["status"] == "REVIEW"
    assert "deferred" in r["reason"].lower()
    assert "16.21" in r["citation"] and "16.22" in r["citation"]


def test_warning_flag_is_confident_violation():
    r = explain(_fr("government_warning", passed=False, inconclusive=False))
    assert r["status"] == "FLAG"
    assert "ALL CAPS" in r["reason"] or "wording differs" in r["reason"].lower()


def test_unknown_field_inconclusive_uses_generic_review():
    r = explain(_fr("mystery", passed=False, inconclusive=True))
    assert r["status"] == "REVIEW" and r["reason"]


def test_warning_absent_review_says_missing_not_present():
    # The 'absent' sub-state must NOT tell the reviewer the warning "appears to be
    # present" (the old generic message) — it's missing on a clear read.
    r = explain(_fr("government_warning", passed=False, inconclusive=True,
                    review_kind="absent"))
    assert r["status"] == "REVIEW"
    assert "missing" in r["reason"].lower()
    assert "present" not in r["reason"].lower()
    assert "non-compliant" in r["what_to_check"].lower()


def test_warning_unreadable_review_says_could_not_read():
    r = explain(_fr("government_warning", passed=False, inconclusive=True,
                    review_kind="unreadable"))
    assert r["status"] == "REVIEW"
    assert "read clearly" in r["reason"].lower() or "didn't read" in r["reason"].lower()
