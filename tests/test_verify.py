"""End-to-end tests over the verify orchestrator (uses real OCR on samples)."""

from pathlib import Path

import pytest

from app.verify import verify_label

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(),
    reason="sample images not generated (run scripts/generate_samples.py)",
)


def _verify(name, brand="Stone's Throw", abv="5.0"):
    return verify_label((SAMPLES / name).read_bytes(), brand=brand, alcohol_content=abv)


def test_clean_pass_all_fields_pass():
    r = _verify("clean_pass.png")
    assert r.readable is True
    assert r.overall_pass is True
    assert {f.field: f.passed for f in r.fields} == {
        "brand": True,
        "alcohol_content": True,
        "government_warning": True,
    }


def test_abv_mismatch_flags_only_alcohol():
    r = _verify("abv_mismatch.png")
    verdicts = {f.field: f.passed for f in r.fields}
    assert verdicts["alcohol_content"] is False
    assert verdicts["brand"] is True
    assert r.overall_pass is False


def test_bad_warning_flags_only_warning():
    r = _verify("bad_warning.png")
    verdicts = {f.field: f.passed for f in r.fields}
    assert verdicts["government_warning"] is False
    assert verdicts["brand"] is True
    assert verdicts["alcohol_content"] is True


def test_unreadable_image_returns_friendly_message():
    # A 1x1 white pixel yields no usable text.
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGB", (1, 1), "white").save(buf, format="PNG")
    r = verify_label(buf.getvalue(), brand="X", alcohol_content="5")
    assert r.readable is False
    assert "couldn't read" in r.message.lower()
    assert not r.fields


def test_non_image_upload_returns_friendly_message():
    # A PDF / HEIC / corrupt file can't be decoded — the user should get the
    # friendly "couldn't read" result, not a 500.
    for blob in (b"%PDF-1.4 not an image", b"\x00\x01\x02 garbage bytes", b""):
        r = verify_label(blob, brand="X", alcohol_content="5")
        assert r.readable is False
        assert "couldn't read" in r.message.lower()
        assert not r.fields


def test_oversized_image_rejected_before_decode(monkeypatch):
    # Guards against decompression bombs: an image over the pixel cap returns
    # the friendly message instead of decoding it.
    from app import ocr

    monkeypatch.setattr(ocr, "MAX_PIXELS", 100)  # any real sample exceeds this
    r = _verify("clean_pass.png")
    assert r.readable is False
    assert "couldn't read" in r.message.lower()


def test_clean_sample_high_confidence_no_review():
    r = _verify("clean_pass.png")
    assert r.confidence > 80
    assert r.needs_review is False


def test_low_confidence_image_needs_review():
    # A heavily blurred (but still readable) label reads at low confidence and
    # should ask for a human rather than committing to a hard verdict.
    from PIL import Image, ImageFilter
    import io

    blurred = Image.open(SAMPLES / "clean_pass.png").convert("RGB").filter(
        ImageFilter.GaussianBlur(3.0)
    )
    buf = io.BytesIO()
    blurred.save(buf, format="PNG")
    r = verify_label(buf.getvalue(), brand="Stone's Throw", alcohol_content="5.0")
    assert r.readable is True
    assert r.needs_review is True
    assert r.confidence < 55
    assert r.overall_pass is False        # needs_review supersedes PASS


def test_uneven_lighting_shadow_is_corrected_and_reads():
    # A left->right darkening gradient (shadow on one side) used to suppress the
    # start of the label: the brand OCR'd as "ne's Throw" (not "Stone's Throw")
    # and the warning header didn't read. CLAHE contrast in the preprocessing
    # pipeline normalizes the uneven lighting so both recover.
    import io
    import numpy as np
    from PIL import Image

    a = np.asarray(Image.open(SAMPLES / "clean_pass.png").convert("RGB")).astype(np.float32)
    ramp = np.linspace(0.45, 1.0, a.shape[1])[None, :, None]          # 0.45x on the left edge
    shadowed = Image.fromarray(np.clip(a * ramp, 0, 255).astype(np.uint8))
    buf = io.BytesIO()
    shadowed.save(buf, format="PNG")
    r = verify_label(buf.getvalue(), brand="Stone's Throw", alcohol_content="5.0")
    verdicts = {f.field: f.passed for f in r.fields}
    assert verdicts["brand"] is True                 # brand recovered from the shadow
    assert verdicts["government_warning"] is True     # warning header recovered too


def test_unreadable_warning_region_defers_to_review_at_high_confidence():
    # The bug this guards: a label whose warning region didn't OCR (header
    # absent) but whose OVERALL mean confidence is high must be routed to NEEDS
    # REVIEW, not a confident FLAG of "warning missing" on a compliant label.
    from app.verify import reverify_text

    text = "Stone's Throw\nCraft Lager\nALC 5.0% BY VOL\n12 FL OZ"  # warning region unread
    r = reverify_text(text, brand="Stone's Throw", alcohol_content="5.0", confidence=95.0)
    assert r.needs_review is True          # inconclusive warning -> defer
    assert r.overall_pass is False


def test_preprocessing_on_keeps_clean_verdicts_no_spurious_review():
    # Regression guard (U3): with OpenCV preprocessing on (default), a clean label
    # still passes all fields and is not pushed below the needs-review threshold.
    r = _verify("clean_pass.png")
    assert r.overall_pass is True
    assert r.needs_review is False
    assert r.confidence > 55


def test_preprocessing_toggle_off_still_verifies(monkeypatch):
    from app import ocr

    monkeypatch.setattr(ocr, "PREPROCESS_ENABLED", False)
    r = _verify("clean_pass.png")
    assert r.overall_pass is True        # master toggle off path works


def test_latency_under_5s_on_each_sample():
    for name in ("clean_pass.png", "abv_mismatch.png", "bad_warning.png"):
        r = _verify(name)
        assert r.elapsed_ms < 5000, f"{name} took {r.elapsed_ms} ms"
