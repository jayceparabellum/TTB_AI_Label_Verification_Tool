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


def test_latency_under_5s_on_each_sample():
    for name in ("clean_pass.png", "abv_mismatch.png", "bad_warning.png"):
        r = _verify(name)
        assert r.elapsed_ms < 5000, f"{name} took {r.elapsed_ms} ms"
