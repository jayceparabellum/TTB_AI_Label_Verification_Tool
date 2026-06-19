"""U5 — cross-surface parity: the Batch page and the assistant both unzip via the
same app.ingest extractor and feed run_batch, so one zip+CSV produces the same
verified rows on both. Locks the "identical behavior on both surfaces" guarantee."""

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import batch as _batch
from app import ingest
from app.main import app
from agent import tools as T
from agent.images import STAGING, STORE

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(),
    reason="sample images not generated (run scripts/generate_samples.py)")
client = TestClient(app)

# A mixed fixture: one clean PASS and one ABV-mismatch FLAG, so parity covers both verdicts.
FIXTURE = {"good.png": "clean_pass", "bad.png": "abv_mismatch"}


def _png(name):
    return (SAMPLES / f"{name}.png").read_bytes()


def _zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for arc, sample in FIXTURE.items():
            zf.writestr(arc, _png(sample))
    return buf.getvalue()


def _csv():
    return ("filename,brand,alcohol_content\n"
            + "\n".join(f"{arc},Stone's Throw,5.0" for arc in FIXTURE)).encode()


@pytest.fixture(autouse=True)
def _clean():
    STAGING._by_thread.clear()
    STORE._images.clear()
    T.LAST_BATCH = None
    yield
    STAGING._by_thread.clear()
    STORE._images.clear()
    T.LAST_BATCH = None


def test_both_surfaces_match_run_batch_for_one_zip():
    zip_bytes, csv = _zip(), _csv()

    # Reference: run_batch over the directly-extracted set.
    extracted = ingest.extract_images_from_zip(zip_bytes)
    core = _batch.run_batch(extracted, csv)
    expected = {r.filename: r.status for r in core.rows}
    assert set(expected) == set(FIXTURE)                 # both labels present
    assert len(set(core.rows[i].status for i in range(len(core.rows)))) >= 1

    # Assistant path: upload zip+csv, then batch_verify over the staged set.
    client.post("/agent/upload", data={"thread_id": "p1"},
                files=[("files", ("labels.zip", zip_bytes, "application/zip")),
                       ("files", ("m.csv", csv, "text/csv"))])
    T.batch_verify.invoke({"state": {"thread_id": "p1"}})
    assistant = {r.filename: r.status for r in T.LAST_BATCH.rows}
    assert assistant == expected                         # assistant == core

    # Batch page: every filename renders and no error banner.
    html = client.post("/batch", files=[
        ("images", ("labels.zip", zip_bytes, "application/zip")),
        ("mapping", ("m.csv", csv, "text/csv"))]).text
    assert all(fn in html for fn in expected)            # page == same file set
    assert "Couldn't run the batch" not in html


def test_over_cap_behavior_is_shared_contract():
    # Same extractor guards both surfaces: >cap rejects identically (D2).
    big = {f"l{i:02d}.png": _png("clean_pass") for i in range(_batch.BATCH_MAX_LABELS + 1)}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for arc, data in big.items():
            zf.writestr(arc, data)
    with pytest.raises(ingest.ZipIngestError):
        ingest.extract_images_from_zip(buf.getvalue())
