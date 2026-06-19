"""Error-handling hardening: fail loud / log / validate / clear messages instead of
silently swallowing (PR #1 spec, implemented on current main)."""

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import ocr
from app.main import app
from app.matching import match_alcohol_content
from app.verify import verify_label

client = TestClient(app)

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
_has_samples = (SAMPLES / "clean_pass.png").exists()


# --- ocr.py -------------------------------------------------------------------
def test_empty_payload_raises_ocr_read_error():
    with pytest.raises(ocr.OcrReadError):
        ocr.extract_text_data(b"")


def test_tesseract_not_found_is_distinct_from_ocr_read_error():
    # A missing-Tesseract deployment error must NOT be a subclass of OcrReadError,
    # so it can't be masked as a per-label "unreadable" result — it surfaces clearly.
    assert not issubclass(ocr.TesseractNotFoundError, ocr.OcrReadError)


# --- verify.py ----------------------------------------------------------------
def test_ocr_failure_is_logged_then_returns_friendly_result(caplog):
    with caplog.at_level(logging.WARNING, logger="app.verify"):
        r = verify_label(b"this is not an image", brand="X", alcohol_content="5.0")
    assert r.readable is False                       # friendly result, no crash
    assert any("OCR failed" in rec.message for rec in caplog.records)


# --- matching.py --------------------------------------------------------------
def test_unparseable_claimed_abv_has_clear_message():
    r = match_alcohol_content("not a number", "ALC 5.0% BY VOL")
    assert r.passed is False
    assert "could not parse" in r.detail.lower()
    assert "not a number" in r.detail               # echoes the offending claimed value


# --- main.py endpoints --------------------------------------------------------
def test_verify_empty_upload_is_400_not_crash():
    r = client.post("/verify",
                    files={"label_image": ("empty.png", b"", "image/png")},
                    data={"brand": "X", "alcohol_content": "5.0"})
    assert r.status_code == 400
    assert "No image was uploaded" in r.text


def test_verify_sample_unknown_key_is_404():
    r = client.post("/verify-sample/does-not-exist")
    assert r.status_code == 404
    assert "Unknown sample" in r.text


@pytest.mark.skipif(not _has_samples, reason="sample images not generated")
def test_verify_sample_known_key_still_works():
    r = client.post("/verify-sample/clean_pass")
    assert r.status_code == 200
