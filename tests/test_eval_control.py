"""T9 — eval control: false-positive metric + real-clean-label loader.

These guard the Six Sigma control plan — the eval must be able to detect the
'clean labels being flagged' defect class, which the synthetic-only board could not.
"""

from pathlib import Path

import pytest

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(),
    reason="sample images not generated (run scripts/generate_samples.py)")


def test_real_clean_loader_ignores_non_images():
    # The drop folder holds only a README until real labels are added -> no cases.
    from eval.run_eval import _real_clean_cases
    assert _real_clean_cases() == []


def test_score_exposes_false_positive_and_negative_counters():
    from eval.cases import CLEAN_CASES
    from eval.run_eval import _score
    s = _score(CLEAN_CASES)
    # Only clean_pass is fully compliant (T,T,T); abv_mismatch and bad_warning are
    # intentionally non-compliant, so compliant==1 and neither error type fires.
    assert s["compliant"] == 1
    assert s["false_pos"] == 0          # the compliant label is not flagged
    assert s["false_neg"] == 0          # no non-compliant label confidently passes
