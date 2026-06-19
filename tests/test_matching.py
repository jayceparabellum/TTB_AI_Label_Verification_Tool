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


def test_long_brand_not_passed_by_short_garbage_candidate():
    # Regression: a candidate SHORTER than the brand must not score 100 just
    # because it appears as a substring of the brand. Garbled OCR "i" used to
    # match the 'i' in "Daniel" and falsely pass "Jack Daniel's" at 100/100.
    assert match_brand("Jack Daniel's", "i, = -").passed is False
    assert match_brand("Jack Daniel's", "a").passed is False
    # The full garbled OCR from a real (unreadable) bottle photo must not pass.
    garbage = "4 ~ » Te >\ni, = -\nP|, oe 'J\nnor :\n& Ten —\nt i} 70cl40%Vol."
    assert match_brand("Jack Daniel's", garbage).passed is False


def test_long_brand_still_matches_when_genuinely_present():
    # The fix must not break real reads: exact, and embedded in a longer line.
    assert match_brand("Jack Daniel's", "JACK DANIEL'S").passed is True
    assert match_brand(
        "Jack Daniel's", "JACK DANIEL'S OLD NO. 7 TENNESSEE WHISKEY"
    ).passed is True


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


def test_warning_drastically_altered_wording_flags_confidently():
    # Wording that is clearly, substantially wrong (well below the review floor)
    # is a confident FLAG.
    altered = ("GOVERNMENT WARNING: This beverage is healthy and completely safe for "
               "everyone, including during pregnancy and before driving.")
    res = match_government_warning(altered)
    assert res.passed is False and res.inconclusive is False
    assert "wording" in res.detail.lower()


def test_warning_minor_alteration_defers_to_review():
    # A small wording change scores ~98% — indistinguishable from OCR noise on a
    # compliant label — so it DEFERS to a human (NEEDS REVIEW) rather than a
    # confident FLAG. Safe by construction: a deferral is never a wrong PASS, and a
    # human still catches the alteration. (Six Sigma false-flag fix, 2026-06-19.)
    altered = OFFICIAL_GOVERNMENT_WARNING.replace("birth defects", "birth defects and harm")
    res = match_government_warning(altered)
    assert res.passed is False and res.inconclusive is True


def test_warning_tolerates_minor_ocr_noise():
    # A 1-2 character OCR slip in the 283-char body must NOT fail a compliant
    # warning. The old exact-substring match did (the dominant false-FLAG bug);
    # a high-threshold fuzzy body match tolerates the noise while staying strict.
    noisy = OFFICIAL_GOVERNMENT_WARNING.replace("operate machinery", "operate machmery")
    assert match_government_warning(noisy).passed is True


def test_warning_unreadable_region_is_inconclusive_not_flag():
    # When the GOVERNMENT WARNING header can't be found at all (the warning
    # region didn't OCR), the matcher must DEFER (inconclusive) so the verdict
    # becomes NEEDS REVIEW — not a confident FLAG asserting non-compliance.
    res = match_government_warning("Stone's Throw  Craft Lager  ALC 5% BY VOL  12 FL OZ")
    assert res.passed is False
    assert res.inconclusive is True


def test_warning_readable_but_wrong_still_flags_confidently():
    # Unambiguous violations stay a confident FLAG (not a deferral): a clearly-read
    # Title-case header (a structural casing violation) and drastically-wrong wording.
    titled = OFFICIAL_GOVERNMENT_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:")
    drastic = ("GOVERNMENT WARNING: This beverage is healthy and completely safe for "
               "everyone, including during pregnancy and before driving.")
    for bad in (titled, drastic):
        res = match_government_warning(bad)
        assert res.passed is False
        assert res.inconclusive is False
