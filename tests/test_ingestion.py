"""Ingestion tests: every way input enters the app, plus format/robustness edges.

Complements test_web.py (UI behaviour) by focusing on *ingestion* — the upload
formats and the bad-input paths that must degrade gracefully (never a 500):
PNG/JPEG/low-res images, corrupt bytes, non-images, oversized images, and the
non-image routes (sample, typed text, re-check, batch).
"""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.reference import OFFICIAL_GOVERNMENT_WARNING

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(),
    reason="sample images not generated (run scripts/generate_samples.py)",
)

client = TestClient(app)
PASS = "PASS &mdash; everything matches"
UNREADABLE = "Couldn't read this image"


def _clean_png() -> bytes:
    return (SAMPLES / "clean_pass.png").read_bytes()


def _verify(image_bytes, filename, content_type, brand="Stone's Throw", abv="5.0"):
    return client.post(
        "/verify",
        data={"brand": brand, "alcohol_content": abv},
        files={"label_image": (filename, image_bytes, content_type)},
    )


# --- Image upload: formats ----------------------------------------------------
def test_ingest_png_upload():
    assert PASS in _verify(_clean_png(), "c.png", "image/png").text


def test_ingest_jpeg_upload():
    buf = io.BytesIO()
    Image.open(io.BytesIO(_clean_png())).convert("RGB").save(buf, "JPEG", quality=90)
    assert PASS in _verify(buf.getvalue(), "c.jpg", "image/jpeg").text


def test_ingest_low_res_is_upscaled_and_read():
    # A small/low-res upload must be ingested (upscaled), not rejected.
    buf = io.BytesIO()
    Image.open(io.BytesIO(_clean_png())).resize((400, 280)).save(buf, "PNG")
    r = _verify(buf.getvalue(), "small.png", "image/png")
    assert r.status_code == 200
    assert UNREADABLE not in r.text          # it was ingested, not rejected


# --- Robustness: bad ingestion is graceful, never a 500 -----------------------
def test_ingest_corrupt_bytes_is_friendly():
    r = _verify(b"not an image at all", "bad.png", "image/png")
    assert r.status_code == 200 and UNREADABLE in r.text


def test_ingest_non_image_is_friendly():
    r = _verify(b"%PDF-1.4 fake pdf bytes", "doc.pdf", "application/pdf")
    assert r.status_code == 200 and UNREADABLE in r.text


def test_ingest_oversized_image_is_rejected_gracefully():
    # 48 MP exceeds the decompression-bomb guard -> friendly message, not a 500.
    buf = io.BytesIO()
    Image.new("RGB", (8000, 6000), "white").save(buf, "PNG")
    r = _verify(buf.getvalue(), "big.png", "image/png")
    assert r.status_code == 200 and UNREADABLE in r.text


# --- Non-image ingestion routes -----------------------------------------------
def test_ingest_known_sample():
    assert PASS in client.post("/verify-sample/clean_pass").text


def test_ingest_unknown_sample_404():
    assert client.post("/verify-sample/does_not_exist").status_code == 404


def test_ingest_typed_label_text():
    label = f"Stone's Throw\nALC 5.0% BY VOL\n{OFFICIAL_GOVERNMENT_WARNING}"
    r = client.post("/verify-text", data={
        "label_text": label, "brand": "Stone's Throw", "alcohol_content": "5.0"})
    assert PASS in r.text


def test_ingest_empty_text_is_friendly():
    r = client.post("/verify-text", data={
        "label_text": "   ", "brand": "X", "alcohol_content": "5"})
    assert "Please paste the label text" in r.text


def test_ingest_recheck_carried_text():
    label = f"Stone's Throw\nALC 5.0% BY VOL\n{OFFICIAL_GOVERNMENT_WARNING}"
    r = client.post("/reverify", data={
        "brand": "Stone's Throw", "alcohol_content": "5.0", "ocr_text": label})
    assert PASS in r.text


# --- Batch ingestion ----------------------------------------------------------
def _img(name):
    return ("images", (f"{name}.png", (SAMPLES / f"{name}.png").read_bytes(), "image/png"))


def test_ingest_batch_images_and_csv():
    csv = (b"filename,brand,alcohol_content\n"
           b"clean_pass.png,Stone's Throw,5.0\nabv_mismatch.png,Stone's Throw,5.0\n")
    files = [_img("clean_pass"), _img("abv_mismatch"), ("mapping", ("m.csv", csv, "text/csv"))]
    r = client.post("/batch", files=files)
    assert r.status_code == 200 and "2 label(s) checked" in r.text


def test_ingest_batch_malformed_csv_is_friendly():
    files = [_img("clean_pass"), ("mapping", ("m.csv", b"garbage header\n", "text/csv"))]
    assert "Couldn't run the batch" in client.post("/batch", files=files).text
