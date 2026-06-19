"""U3 — Batch page accepts a .zip of label photos (additive to loose images)."""

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.batch import BATCH_MAX_LABELS
from app.main import app

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(),
    reason="sample images not generated (run scripts/generate_samples.py)")
client = TestClient(app)


def _png(name="clean_pass"):
    return (SAMPLES / f"{name}.png").read_bytes()


def _zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _csv(names):
    return ("filename,brand,alcohol_content\n" + "\n".join(
        f"{n},Stone's Throw,5.0" for n in names)).encode()


def _post(zip_bytes=None, loose=None, csv_names=None):
    files = []
    if zip_bytes is not None:
        files.append(("images", ("labels.zip", zip_bytes, "application/zip")))
    for nm in (loose or []):
        files.append(("images", (nm, _png(), "image/png")))
    files.append(("mapping", ("m.csv", _csv(csv_names), "text/csv")))
    return client.post("/batch", files=files)


def test_zip_of_25_processes_all_25():
    names = [f"label_{i:02d}.png" for i in range(BATCH_MAX_LABELS)]
    html = _post(zip_bytes=_zip({n: _png() for n in names}), csv_names=names).text
    missing = [n for n in names if n not in html]
    assert not missing, f"{BATCH_MAX_LABELS - len(missing)}/{BATCH_MAX_LABELS} processed"


def test_zip_plus_loose_images_merge():
    znames = ["z1.png", "z2.png", "z3.png"]
    loose = ["loose1.png", "loose2.png"]
    html = _post(zip_bytes=_zip({n: _png() for n in znames}),
                 loose=loose, csv_names=znames + loose).text
    assert all(n in html for n in znames + loose)


def test_over_cap_zip_is_friendly_error_not_500():
    names = [f"l{i:02d}.png" for i in range(BATCH_MAX_LABELS + 1)]
    r = _post(zip_bytes=_zip({n: _png() for n in names}), csv_names=names)
    assert r.status_code == 200
    assert "Couldn't run the batch" in r.text and str(BATCH_MAX_LABELS) in r.text


def test_corrupt_zip_is_friendly_error():
    r = _post(zip_bytes=b"not a real zip", csv_names=["x.png"])
    assert r.status_code == 200
    assert "Couldn't run the batch" in r.text


def test_loose_only_upload_still_works():
    # Regression: the pre-existing multi-file path is unchanged.
    html = _post(loose=["a.png", "b.png"], csv_names=["a.png", "b.png"]).text
    assert "a.png" in html and "b.png" in html
