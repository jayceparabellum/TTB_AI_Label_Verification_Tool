"""Unit tests for the OpenCV preprocessing steps (U2)."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app import preprocess as pp

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(),
    reason="sample images not generated (run scripts/generate_samples.py)",
)


def _gray(name="clean_pass"):
    return np.array(Image.open(SAMPLES / f"{name}.png").convert("L"))


# --- deskew (the risky step) --------------------------------------------------
def test_deskew_corrects_known_rotation():
    rotated = np.array(
        Image.open(SAMPLES / "clean_pass.png").convert("L").rotate(10, expand=True, fillcolor=255)
    )
    before = abs(pp.detect_skew_angle(rotated))
    corrected, applied = pp.deskew(rotated)
    after = abs(pp.detect_skew_angle(corrected))
    assert before > 5            # the rotation was detected
    assert after < 2             # straightened close to 0
    assert after < before        # strictly improved


def test_deskew_noop_on_straight_image():
    gray = _gray()
    angle = pp.detect_skew_angle(gray)
    corrected, applied = pp.deskew(gray)
    assert abs(angle) < pp.DESKEW_MIN_ANGLE        # essentially straight
    assert np.array_equal(corrected, gray)         # not rotated at all


# --- binarize -----------------------------------------------------------------
def test_binarize_is_two_valued_and_preserves_text():
    out = pp.binarize(_gray())
    assert set(np.unique(out)).issubset({0, 255})  # binary
    assert out.min() == 0 and out.max() == 255     # has both ink and paper (not blank)


# --- contrast / denoise return valid images -----------------------------------
def test_contrast_and_denoise_return_same_shape_uint8():
    gray = _gray()
    for fn in (pp.denoise, pp.contrast):
        out = fn(gray)
        assert out.shape == gray.shape
        assert out.dtype == np.uint8


# --- full pipeline + per-step toggles -----------------------------------------
def test_preprocess_runs_and_respects_toggles(monkeypatch):
    gray = _gray()
    out = pp.preprocess(gray)
    assert out.shape == gray.shape and out.dtype == np.uint8

    # With every step off, preprocess is the identity.
    monkeypatch.setattr(pp, "STEPS", {k: False for k in pp.STEPS})
    assert np.array_equal(pp.preprocess(gray), gray)
