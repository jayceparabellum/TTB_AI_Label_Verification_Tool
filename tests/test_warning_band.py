"""T6 — government-warning NEEDS-REVIEW band.

The core false-positive fix (Six Sigma verification, 2026-06-19): a compliant-but-
noisy warning must DEFER to a human (inconclusive -> NEEDS REVIEW), never confident-
FLAG. Genuine violations (Title-case header, drastically altered wording) still FLAG.
A defer can never become a wrong PASS, so this never weakens compliance detection.
"""

from app.matching import (
    WARNING_REVIEW_FLOOR,
    WARNING_SIMILARITY_THRESHOLD,
    match_government_warning as mw,
)
from app.reference import OFFICIAL_GOVERNMENT_WARNING as W


def test_clean_allcaps_warning_passes():
    r = mw(W)
    assert r.passed is True and r.inconclusive is False


def test_noisy_but_present_warning_defers_not_flags():
    # A few characters of OCR noise on the body (header intact, ALL CAPS) -> the
    # old rule confident-FLAGged this compliant label; now it defers to review.
    noisy = W[:150] + "xxxxxx" + W[156:]            # ~6 corrupted chars in the body
    r = mw(noisy)
    assert r.passed is False
    assert r.inconclusive is True                   # NEEDS REVIEW, not FLAG


def test_drastically_altered_wording_still_flags():
    altered = ("GOVERNMENT WARNING: This product is perfectly safe to drink in "
               "unlimited quantities and carries no health risks whatsoever.")
    r = mw(altered)
    assert r.passed is False
    assert r.inconclusive is False                  # confident FLAG (genuinely wrong)


def test_titlecase_header_still_flags_as_casing_violation():
    titled = W.replace("GOVERNMENT WARNING:", "Government Warning:")
    r = mw(titled)
    assert r.passed is False
    assert r.inconclusive is False                  # crisp 27 CFR 16.22 violation
    assert "ALL CAPS" in r.found


def test_no_warning_region_defers():
    r = mw("Cedar Hollow\nCraft Lager\nALC 5.0% BY VOL\n12 FL OZ")
    assert r.passed is False and r.inconclusive is True


def test_band_thresholds_ordered():
    assert WARNING_REVIEW_FLOOR < WARNING_SIMILARITY_THRESHOLD
