"""U4 — the assistant ingests a .zip (+ CSV): unzip, stage every image, and
batch_verify runs over the full set with parity to run_batch."""

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import batch as _batch
from app.batch import BATCH_MAX_LABELS
from app.main import app
from agent import tools as T
from agent.images import STAGING, STORE

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


@pytest.fixture(autouse=True)
def _clean():
    STAGING._by_thread.clear()
    STORE._images.clear()
    T.LAST_BATCH = None
    yield
    STAGING._by_thread.clear()
    STORE._images.clear()
    T.LAST_BATCH = None


def _upload(thread, zip_bytes=None, csv=None):
    files = []
    if zip_bytes is not None:
        files.append(("files", ("labels.zip", zip_bytes, "application/zip")))
    if csv is not None:
        files.append(("files", ("m.csv", csv, "text/csv")))
    return client.post("/agent/upload", data={"thread_id": thread}, files=files)


def test_zip_unzips_and_stages_every_image():
    names = [f"label_{i:02d}.png" for i in range(BATCH_MAX_LABELS)]
    r = _upload("z1", zip_bytes=_zip({n: _png() for n in names}))
    item = r.json()["items"][0]
    assert item["kind"] == "zip" and item["extracted"] == BATCH_MAX_LABELS
    staged = STAGING.get_batch("z1")
    # get_batch needs a CSV present; stage one then re-check the image set.
    assert staged is None              # no CSV yet -> no batch
    assert len(STAGING._by_thread["z1"]["batch_images"]) == BATCH_MAX_LABELS


def test_zip_plus_csv_batch_verify_matches_run_batch():
    names = ["a.png", "b.png", "c.png"]
    csv = ("filename,brand,alcohol_content\n" + "\n".join(
        f"{n},Stone's Throw,5.0" for n in names)).encode()
    _upload("z2", zip_bytes=_zip({n: _png() for n in names}), csv=csv)
    staged = STAGING.get_batch("z2")
    assert staged is not None and len(staged["images"]) == 3

    out = T.batch_verify.invoke({"state": {"thread_id": "z2"}})
    assert out["source"] == "uploaded" and out["total"] == 3
    # Parity: the staged set verifies identically to run_batch over the same bytes.
    core = _batch.run_batch([(n, _png()) for n in names], csv)
    assert {r.filename: r.status for r in T.LAST_BATCH.rows} == \
        {r.filename: r.status for r in core.rows}


def test_over_cap_zip_rejected_nothing_staged():
    names = [f"l{i:02d}.png" for i in range(BATCH_MAX_LABELS + 1)]
    r = _upload("z3", zip_bytes=_zip({n: _png() for n in names}))
    item = r.json()["items"][0]
    assert item["kind"] == "rejected" and str(BATCH_MAX_LABELS) in item["reason"]
    assert "z3" not in STAGING._by_thread or not STAGING._by_thread["z3"]["batch_images"]


def test_corrupt_zip_rejected_no_500():
    r = _upload("z4", zip_bytes=b"definitely not a zip")
    assert r.status_code == 200
    assert r.json()["items"][0]["kind"] == "rejected"


def test_zip_bytes_count_toward_thread_cap_and_evict_on_reset():
    names = ["a.png", "b.png"]
    _upload("z5", zip_bytes=_zip({n: _png() for n in names}))
    from app import main as main_mod
    assert main_mod._thread_bytes("z5") > 0          # extracted images counted
    assert client.post("/agent/reset", data={"thread_id": "z5"}).json()["ok"] is True
    assert main_mod._thread_bytes("z5") == 0         # reset evicted them
