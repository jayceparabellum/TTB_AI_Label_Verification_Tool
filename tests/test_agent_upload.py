"""In-chat upload — U1 per-thread staging + U2 /agent/upload endpoint. Images stash
in the session by id, non-images get a friendly rejection, caps hold, and reset
evicts the thread's bytes. All in-process, no disk."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.images import STAGING, STORE
from app.main import app

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(), reason="sample images not generated")
client = TestClient(app)


def _png():
    return (SAMPLES / "clean_pass.png").read_bytes()


# --- U1: staging store -------------------------------------------------------
def test_staging_clear_evicts_image_bytes():
    STAGING._by_thread.clear()
    iid = STORE.put(b"abc")
    STAGING.add_image("t1", iid)
    assert STORE.get(iid) == b"abc"
    STAGING.clear("t1")
    assert STORE.get(iid) is None              # clear evicted the bytes
    assert STAGING.get_batch("t1") is None


# --- U2: upload endpoint -----------------------------------------------------
def test_upload_image_stashes_and_returns_id():
    r = client.post("/agent/upload", data={"thread_id": "tu1"},
                    files=[("files", ("label.png", _png(), "image/png"))])
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["kind"] == "image" and item["name"] == "label.png"
    assert STORE.get(item["id"]) == _png()     # bytes really stashed, retrievable by id


def test_upload_wellformed_csv_is_staged_with_rowcount():
    # U5: a valid mapping CSV is accepted and staged as the thread's batch.
    STAGING._by_thread.clear()
    csv = b"filename,brand,alcohol_content\na.png,Acme,5.0\nb.png,Beta,12.5\n"
    r = client.post("/agent/upload", data={"thread_id": "tu2"},
                    files=[("files", ("map.csv", csv, "text/csv"))])
    assert r.status_code == 200
    it = r.json()["items"][0]
    assert it["kind"] == "csv" and it["rows"] == 2
    assert STAGING.get_batch("tu2")["csv"] == csv      # really staged for the run


def test_upload_malformed_csv_is_friendly_rejected_not_500():
    # A CSV missing a required column is rejected with the core's message, no 500.
    r = client.post("/agent/upload", data={"thread_id": "tu2b"},
                    files=[("files", ("b.csv", b"filename,brand\n", "text/csv"))])
    assert r.status_code == 200
    it = r.json()["items"][0]
    assert it["kind"] == "rejected" and "alcohol_content" in it["reason"]


def test_upload_unknown_type_rejected_no_500():
    r = client.post("/agent/upload", data={"thread_id": "tu3"},
                    files=[("files", ("x.pdf", b"%PDF-1.4 not an image", "application/pdf"))])
    assert r.status_code == 200
    assert r.json()["items"][0]["kind"] == "rejected"


def test_upload_oversized_rejected():
    big = b"\x89PNG" + b"0" * (10 * 1024 * 1024 + 10)   # > 10 MB
    r = client.post("/agent/upload", data={"thread_id": "tu4"},
                    files=[("files", ("big.png", big, "image/png"))])
    it = r.json()["items"][0]
    assert it["kind"] == "rejected" and "max" in it["reason"].lower()


def test_reset_evicts_thread_bytes():
    r = client.post("/agent/upload", data={"thread_id": "tu5"},
                    files=[("files", ("l.png", _png(), "image/png"))])
    iid = r.json()["items"][0]["id"]
    assert STORE.get(iid) is not None
    assert client.post("/agent/reset", data={"thread_id": "tu5"}).json()["ok"] is True
    assert STORE.get(iid) is None
