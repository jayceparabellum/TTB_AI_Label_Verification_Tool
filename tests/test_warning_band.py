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


def test_missing_warning_on_clear_read_classified_absent():
    # A label that read clearly (high confidence) with no warning anywhere is
    # classified "absent" — it appears genuinely missing. Still DEFERS (never a
    # confident FLAG: mean confidence is a whole-image signal and can't prove the
    # warning region itself wasn't dropped).
    text = "Cedar Hollow\nCraft Lager\nALC 5.0% BY VOL\n12 FL OZ"
    r = mw(text, confidence=92.0)
    assert r.passed is False and r.inconclusive is True
    assert r.review_kind == "absent"
    assert "missing" in r.found.lower()


def test_missing_warning_on_shaky_read_classified_unreadable():
    # The same absence on a low-confidence read is "unreadable" — we can't trust
    # that we'd have seen the warning, so it's a read problem, not a missing-warning
    # finding.
    text = "Cedar Hollow\nCraft Lager\nALC 5.0% BY VOL\n12 FL OZ"
    r = mw(text, confidence=20.0)
    assert r.passed is False and r.inconclusive is True
    assert r.review_kind == "unreadable"


def test_absent_classification_keys_off_the_ocr_trust_threshold():
    # The split uses the OCR confidence floor as the single source of truth for
    # "do we trust this read", so the warning matcher and the global needs-review
    # signal agree on what "trustworthy" means.
    from app.ocr import OCR_CONFIDENCE_THRESHOLD
    text = "Cedar Hollow\nCraft Lager\nALC 5.0% BY VOL\n12 FL OZ"
    assert mw(text, confidence=OCR_CONFIDENCE_THRESHOLD).review_kind == "absent"
    assert mw(text, confidence=OCR_CONFIDENCE_THRESHOLD - 1).review_kind == "unreadable"


def test_present_but_noisy_warning_is_unreadable_not_absent():
    # A present-but-noisy warning (header intact, body below the cutoff) defers as
    # "unreadable" — it's there but couldn't be confirmed, not missing.
    noisy = W[:150] + "xxxxxx" + W[156:]
    r = mw(noisy, confidence=92.0)
    assert r.passed is False and r.inconclusive is True
    assert r.review_kind == "unreadable"


def test_dropped_negation_does_not_confidently_pass():
    # Regression (Six Sigma review): removing 'not' from "should not drink" inverts
    # the meaning but scores ~99% on character overlap. It must NOT confidently PASS
    # (a wrong PASS on a non-compliant warning is the worst, regulatory-miss error).
    inverted = W.replace("should not drink", "should drink")
    r = mw(inverted)
    assert r.passed is False                # never a confident PASS
    assert r.inconclusive is True           # defers to a human instead


def test_one_char_ocr_noise_still_passes():
    # The word-completeness guard must not over-reject genuine compliant reads with
    # a character of OCR noise (each word still fuzzily matches).
    noisy = W.replace("operate machinery", "operate machmery")
    assert mw(noisy).passed is True


def test_band_thresholds_ordered():
    assert WARNING_REVIEW_FLOOR < WARNING_SIMILARITY_THRESHOLD
