"""U6 — session hygiene: the per-thread upload cap counts images AND the staged
CSV, an over-large cumulative upload is friendly-rejected (no 500), and reset/clear
evicts every byte a thread staged (images + batch). All in-process, no disk."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as main_mod
from agent.images import STAGING, STORE
from app.main import app

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(), reason="sample images not generated")
client = TestClient(app)


def _png():
    return (SAMPLES / "clean_pass.png").read_bytes()


@pytest.fixture(autouse=True)
def _clean():
    STAGING._by_thread.clear()
    STORE._images.clear()
    yield
    STAGING._by_thread.clear()
    STORE._images.clear()


def test_thread_byte_count_includes_staged_csv():
    t = "tb1"
    csv = b"filename,brand,alcohol_content\na.png,Acme,5.0\n"
    client.post("/agent/upload", data={"thread_id": t},
                files=[("files", ("m.csv", csv, "text/csv"))])
    client.post("/agent/upload", data={"thread_id": t},
                files=[("files", ("a.png", _png(), "image/png"))])
    assert main_mod._thread_bytes(t) == len(csv) + len(_png())   # both counted


def test_cap_rejects_when_cumulative_exceeds_thread_limit(monkeypatch):
    # Shrink the per-thread cap so a single sample PNG overflows the second upload.
    monkeypatch.setattr(main_mod, "_MAX_THREAD_BYTES", len(_png()) + 100)
    t = "tb2"
    first = client.post("/agent/upload", data={"thread_id": t},
                        files=[("files", ("a.png", _png(), "image/png"))])
    assert first.json()["items"][0]["kind"] == "image"          # under cap
    second = client.post("/agent/upload", data={"thread_id": t},
                         files=[("files", ("b.png", _png(), "image/png"))])
    it = second.json()["items"][0]
    assert second.status_code == 200                            # friendly, not a 500
    assert it["kind"] == "rejected" and "limit" in it["reason"].lower()


def test_reset_evicts_images_and_staged_batch():
    t = "tb3"
    csv = b"filename,brand,alcohol_content\na.png,Acme,5.0\n"
    r = client.post("/agent/upload", data={"thread_id": t},
                    files=[("files", ("a.png", _png(), "image/png")),
                           ("files", ("m.csv", csv, "text/csv"))])
    iid = next(i["id"] for i in r.json()["items"] if i["kind"] == "image")
    assert STORE.get(iid) is not None
    assert STAGING.get_batch(t) is not None

    assert client.post("/agent/reset", data={"thread_id": t}).json()["ok"] is True
    assert STORE.get(iid) is None                               # image bytes gone
    assert STAGING.get_batch(t) is None                         # staged batch gone
    assert main_mod._thread_bytes(t) == 0                       # nothing left
