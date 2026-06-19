"""Web-layer tests for the UI features (drag-drop scaffold, thumbnail, re-check)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.reference import OFFICIAL_GOVERNMENT_WARNING
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


# --- Detailed per-flag reasons section (T8) -----------------------------------
def test_flagged_field_shows_detailed_reason_and_citation():
    # abv_mismatch flags the alcohol field -> the results page must explain WHY,
    # with what-to-check guidance and the controlling 27 CFR citation.
    r = client.post("/verify-sample/abv_mismatch")
    assert "Why this FLAG" in r.text
    assert "What to check:" in r.text
    assert "§4.36" in r.text                       # controlling alcohol-content reg


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


# --- U5/U6: confidence "needs review" cue --------------------------------------
def test_reverify_low_confidence_shows_needs_review_banner():
    text = _ocr_text("clean_pass")
    r = client.post("/reverify", data={
        "brand": "Stone's Throw", "alcohol_content": "5.0",
        "ocr_text": text, "confidence": "20",
    })
    assert "NEEDS REVIEW" in r.text
    assert "banner-review" in r.text


# --- Type-a-label (no image, no OCR) ------------------------------------------
def test_text_form_renders():
    html = client.get("/text").text
    assert 'name="label_text"' in html and 'action="/verify-text"' in html


def test_verify_text_pass():
    label = f"Stone's Throw\nALC 5.0% BY VOL\n{OFFICIAL_GOVERNMENT_WARNING}"
    r = client.post("/verify-text", data={
        "label_text": label, "brand": "Stone's Throw", "alcohol_content": "5.0"})
    assert "PASS &mdash; everything matches" in r.text


def test_verify_text_wrong_brand_flags():
    label = f"Stone's Throw\nALC 5.0% BY VOL\n{OFFICIAL_GOVERNMENT_WARNING}"
    r = client.post("/verify-text", data={
        "label_text": label, "brand": "Totally Different Co", "alcohol_content": "5.0"})
    assert "FLAGGED" in r.text


def test_verify_text_empty_is_friendly():
    r = client.post("/verify-text", data={
        "label_text": "   ", "brand": "X", "alcohol_content": "5"})
    assert "Please paste the label text" in r.text


# --- Batch verification web flow (U2/U3) --------------------------------------
def _sample_file(field, name):
    return (field, (f"{name}.png", (SAMPLES / f"{name}.png").read_bytes(), "image/png"))


def test_batch_form_lists_inputs_and_cap():
    html = client.get("/batch").text
    assert 'name="images"' in html and "multiple" in html
    assert 'name="mapping"' in html
    assert "batch-template.csv" in html


def test_batch_run_renders_table_and_summary():
    csv = b"filename,brand,alcohol_content\nclean_pass.png,Stone's Throw,5.0\nabv_mismatch.png,Stone's Throw,5.0\n"
    files = [
        _sample_file("images", "clean_pass"),
        _sample_file("images", "abv_mismatch"),
        ("mapping", ("m.csv", csv, "text/csv")),
    ]
    r = client.post("/batch", files=files)
    assert r.status_code == 200
    assert "2 label(s) checked" in r.text
    assert "clean_pass.png" in r.text and "abv_mismatch.png" in r.text
    assert "attnFilter" in r.text                      # filter control present
    assert "Download results CSV" in r.text            # U3 export link


def test_batch_run_malformed_csv_is_friendly():
    files = [_sample_file("images", "clean_pass"),
             ("mapping", ("m.csv", b"no proper header here\n", "text/csv"))]
    r = client.post("/batch", files=files)
    assert r.status_code == 200
    assert "Couldn't run the batch" in r.text


def test_batch_run_over_cap_message():
    files = [_sample_file("images", "clean_pass") for _ in range(26)]
    files.append(("mapping", ("m.csv", b"filename,brand,alcohol_content\nclean_pass.png,X,5\n", "text/csv")))
    r = client.post("/batch", files=files)
    assert "limited to 25" in r.text


def test_upload_low_confidence_shows_needs_review_banner():
    from PIL import Image, ImageFilter
    import io

    blurred = Image.open(SAMPLES / "clean_pass.png").convert("RGB").filter(
        ImageFilter.GaussianBlur(3.0)
    )
    buf = io.BytesIO()
    blurred.save(buf, format="PNG")
    buf.seek(0)
    r = client.post(
        "/verify",
        data={"brand": "Stone's Throw", "alcohol_content": "5.0"},
        files={"label_image": ("blur.png", buf, "image/png")},
    )
    assert "NEEDS REVIEW" in r.text
