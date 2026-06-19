"""U1 — characterization of the batch file-count path.

A reported defect: a single 25-label transaction only processes ~4 labels. There is
no static explanation (no cap/slice in the batch path; Starlette's multipart max_files
default is 1000), so this test pins the real behavior at the HTTP boundary: POST 25
distinct image parts + a 25-row CSV to /batch and assert all 25 are processed.

If this passes, the loose-file multipart path is sound and the truncation (if any) is
specific to the not-yet-built ZIP workflow — recorded here so U3/U4 carry the 25-count
guarantee for zips. If it fails, it localizes the limiter.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(),
    reason="sample images not generated (run scripts/generate_samples.py)")
client = TestClient(app)

N = 25
_PNG = None


def _png():
    global _PNG
    if _PNG is None:
        _PNG = (SAMPLES / "clean_pass.png").read_bytes()
    return _PNG


def _names(n=N):
    return [f"label_{i:02d}.png" for i in range(n)]


def _multipart(names):
    files = [("images", (nm, _png(), "image/png")) for nm in names]
    csv = "filename,brand,alcohol_content\n" + "\n".join(
        f"{nm},Stone's Throw,5.0" for nm in names)
    files.append(("mapping", ("m.csv", csv.encode(), "text/csv")))
    return files


def test_twentyfive_loose_files_all_processed():
    names = _names(N)
    html = client.post("/batch", files=_multipart(names)).text
    missing = [nm for nm in names if nm not in html]
    assert not missing, f"{N - len(missing)}/{N} processed; missing: {missing[:8]}"


@pytest.mark.parametrize("n", [1, N])
def test_boundary_counts_all_processed(n):
    names = _names(n)
    html = client.post("/batch", files=_multipart(names)).text
    assert all(nm in html for nm in names)
