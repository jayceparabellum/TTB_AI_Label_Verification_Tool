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
