"""Web-layer tests for the UI features (drag-drop scaffold, thumbnail, re-check)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.verify import verify_label

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(),
    reason="sample images not generated (run scripts/generate_samples.py)",
)

client = TestClient(app)


def _ocr_text(key, brand="Stone's Throw", abv="5.0"):
    img = (SAMPLES / f"{key}.png").read_bytes()
    return verify_label(img, brand=brand, alcohol_content=abv).ocr_text


# --- U1: upload screen ---------------------------------------------------------
def test_index_has_dropzone_and_script():
    html = client.get("/").text
    assert 'id="dropzone"' in html
    assert "/static/upload.js" in html
    assert html.count("Check this sample") == 3


# --- U2: thumbnail on results --------------------------------------------------
def test_upload_results_embed_thumbnail_data_uri():
    with (SAMPLES / "clean_pass.png").open("rb") as fh:
        r = client.post(
            "/verify",
            data={"brand": "STONE'S THROW", "alcohol_content": "5.0"},
            files={"label_image": ("clean_pass.png", fh, "image/png")},
        )
    assert r.status_code == 200
    assert "data:image/jpeg;base64," in r.text          # small inline thumbnail
    assert "PASS &mdash; everything matches" in r.text


def test_sample_results_use_static_image_url():
    r = client.post("/verify-sample/clean_pass")
    assert "/static/samples/clean_pass.png" in r.text     # sample uses static URL
    assert "data:image/jpeg" not in r.text


# --- U3: print control ---------------------------------------------------------
def test_results_have_print_control():
    r = client.post("/verify-sample/clean_pass")
    assert "Print / Save" in r.text
    assert 'onclick="window.print()"' in r.text


# --- U4: inline re-check (matchers on carried OCR text, no re-OCR) --------------
def test_results_carry_ocr_text_and_recheck_form():
    r = client.post("/verify-sample/abv_mismatch")
    assert 'action="/reverify"' in r.text
    assert 'name="ocr_text"' in r.text


def test_reverify_corrected_abv_now_passes():
    text = _ocr_text("abv_mismatch")            # label prints 7.5%
    r = client.post("/reverify", data={
        "brand": "Stone's Throw", "alcohol_content": "7.5", "ocr_text": text,
    })
    assert "PASS &mdash; everything matches" in r.text


def test_reverify_consistency_unchanged_inputs_reproduce_verdict():
    # Same inputs + same carried text must reproduce the original verdict exactly.
    text = _ocr_text("clean_pass")
    r = client.post("/reverify", data={
        "brand": "Stone's Throw", "alcohol_content": "5.0", "ocr_text": text,
    })
    assert "PASS &mdash; everything matches" in r.text


def test_reverify_wrong_brand_flags():
    text = _ocr_text("clean_pass")
    r = client.post("/reverify", data={
        "brand": "Totally Different Co", "alcohol_content": "5.0", "ocr_text": text,
    })
    assert "FLAGGED" in r.text


def test_reverify_empty_text_returns_friendly_message():
    r = client.post("/reverify", data={
        "brand": "X", "alcohol_content": "5", "ocr_text": "",
    })
    assert "Couldn't read this image" in r.text
