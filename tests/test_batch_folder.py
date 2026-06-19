"""F1 — /batch tolerates a picked folder (webkitdirectory): non-image junk is
skipped, and folder-relative filenames match the CSV by basename."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(),
    reason="sample images not generated (run scripts/generate_samples.py)")
client = TestClient(app)


def _png():
    return (SAMPLES / "clean_pass.png").read_bytes()


def _csv(names):
    return ("filename,brand,alcohol_content\n" + "\n".join(
        f"{n},Stone's Throw,5.0" for n in names)).encode()


def test_folder_upload_skips_junk_and_matches_by_basename():
    # A webkitdirectory pick sends folder-relative paths + OS junk files.
    files = [
        ("images", ("labels/clean_pass.png", _png(), "image/png")),       # relative path
        ("images", ("labels/abv_mismatch.png", (SAMPLES / "abv_mismatch.png").read_bytes(), "image/png")),
        ("images", ("labels/.DS_Store", b"\x00\x01junk", "application/octet-stream")),
        ("images", ("labels/notes.txt", b"not an image", "text/plain")),
        ("mapping", ("m.csv", _csv(["clean_pass.png", "abv_mismatch.png"]), "text/csv")),
    ]
    html = client.post("/batch", files=files).text
    assert html.count("Couldn't run the batch") == 0
    # Both images verified, matched by basename (not the folder-relative path)…
    assert "clean_pass.png" in html and "abv_mismatch.png" in html
    # …and the junk files were skipped (not rendered as rows / errors).
    assert ".DS_Store" not in html and "notes.txt" not in html


def test_loose_image_upload_still_works():
    # Regression: the plain multi-file path (basenames already) is unaffected.
    files = [("images", ("clean_pass.png", _png(), "image/png")),
             ("mapping", ("m.csv", _csv(["clean_pass.png"]), "text/csv"))]
    assert "clean_pass.png" in client.post("/batch", files=files).text
