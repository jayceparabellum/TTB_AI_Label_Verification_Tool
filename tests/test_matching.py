"""Unit tests for the matching logic — the <1% decision-logic accuracy evidence.

These run on known text (no OCR), so they isolate the decision logic from OCR
legibility, exactly as the error budget is scoped.
"""

import pytest

from app.matching import (
    match_alcohol_content,
    match_brand,
    match_government_warning,
)
from app.reference import OFFICIAL_GOVERNMENT_WARNING


# --- Brand (fuzzy / tolerant) -------------------------------------------------
@pytest.mark.parametrize(
    "expected, ocr_text, should_pass",
    [
        ("Stone's Throw", "STONE'S THROW", True),      # case + punctuation
        ("Stone's Throw", "Stone's Throw", True),
        ("Stone's Throw", "stones throw", True),        # punctuation + case
        ("Stone's Throw", "STONE'S THROW BREWING CO", True),  # embedded in line
        ("Stone's Throw", "Riverbend Brewing", False),  # different brand
        ("Stone's Throw", "", False),                   # nothing
    ],
)
def test_brand(expected, ocr_text, should_pass):
    assert match_brand(expected, ocr_text).passed is should_pass


def test_short_brand_not_falsely_matched_by_substring():
    # A short brand must not pass just because its letters appear as a
    # substring somewhere on a busy label (partial_ratio false positive).
    assert match_brand("Bud", "STONE'S THROW BREWING CO\nPALE ALE\n12 FL OZ").passed is False
    # but a short brand that genuinely appears still passes
    assert match_brand("Bud", "BUD").passed is True


# --- Alcohol content (numeric, proof-aware) -----------------------------------
@pytest.mark.parametrize(
    "claimed, ocr_text, should_pass",
    [
        ("5.0", "ALC 5% BY VOL", True),
        ("5.0", "5.0% ABV", True),
        ("5.0", "5% ALC/VOL", True),
        ("5.0", "10 PROOF", True),          # proof = 2x ABV
        ("5.0", "ALC 7.5% BY VOL", False),  # genuine mismatch
        ("5.0", "no alcohol statement here", False),
        ("40", "80 PROOF", True),           # spirits
    ],
)
def test_alcohol_content(claimed, ocr_text, should_pass):
    assert match_alcohol_content(claimed, ocr_text).passed is should_pass


def test_alcohol_ignores_unrelated_percentage():
    # The real alcohol content (8%) mismatches the claim; a stray "5%" that is
    # NOT in alcohol context must not create a false PASS.
    label = "ALC 8% BY VOL.\nContains 5% real fruit juice. 12 FL OZ"
    res = match_alcohol_content("5.0", label)
    assert res.passed is False
    assert "8%" in res.found


def test_alcohol_found_shows_the_matching_value():
    # When proof drives the match, the displayed 'found' must reflect it, not a
    # different percentage also present on the label.
    res = match_alcohol_content("40", "ALC 10% SERVING ... 80 proof")
    assert res.passed is True
    assert "proof" in res.found.lower() or "40" in res.found


# --- Government warning (strict) ----------------------------------------------
def test_warning_exact_passes():
    # Even with OCR-style line wrapping (whitespace differences) it passes.
    wrapped = OFFICIAL_GOVERNMENT_WARNING.replace(" ", "\n", 5)
    assert match_government_warning(wrapped).passed is True


def test_warning_title_case_fails():
    titled = OFFICIAL_GOVERNMENT_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:")
    res = match_government_warning(titled)
    assert res.passed is False
    assert "ALL CAPS" in res.found


def test_warning_altered_wording_fails():
    altered = OFFICIAL_GOVERNMENT_WARNING.replace("birth defects", "birth defects and harm")
    res = match_government_warning(altered)
    assert res.passed is False
    assert "wording" in res.detail.lower()


def test_warning_missing_fails():
    res = match_government_warning("Brand X Craft Lager  ALC 5% BY VOL  12 FL OZ")
    assert res.passed is False
    assert "missing" in res.detail.lower()
