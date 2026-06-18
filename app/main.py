"""FastAPI app: one upload screen, one results screen.

Kept deliberately small and server-rendered (Jinja2 + vanilla CSS, no JS build)
so the UI is large-target, obvious, and usable by the least tech-comfortable
agent. Stateless: nothing is persisted; each request is processed and discarded.
"""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import batch as batch_mod
from . import ocr
from .models import VerificationResult
from .reference import OFFICIAL_GOVERNMENT_WARNING
from .samples import SAMPLES
from .verify import UNREADABLE_MESSAGE, reverify_text, verify_label

BASE_DIR = Path(__file__).parent

app = FastAPI(title="TTB Label Verification", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "samples": list(SAMPLES.values()),
            "official_warning": OFFICIAL_GOVERNMENT_WARNING,
        },
    )


def _render_result(
    request: Request,
    result,
    brand: str,
    alcohol_content: str,
    *,
    image_src: str | None = None,
    ocr_text: str = "",
    expected_warning: str = OFFICIAL_GOVERNMENT_WARNING,
    error: str | None = None,
    status_code: int = 200,
):
    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "result": result,
            "brand": brand,
            "alcohol_content": alcohol_content,
            "image_src": image_src,          # data URI (upload) or static URL (sample)
            "ocr_text": ocr_text,            # carried for re-check (U4)
            "expected_warning": expected_warning,
            "error": error,
        },
        status_code=status_code,
    )


@app.post("/verify", response_class=HTMLResponse)
async def verify(
    request: Request,
    label_image: UploadFile = File(...),
    brand: str = Form(...),
    alcohol_content: str = Form(...),
    expected_warning: str = Form(OFFICIAL_GOVERNMENT_WARNING),
):
    image_bytes = await label_image.read()
    warning = expected_warning or OFFICIAL_GOVERNMENT_WARNING
    result = verify_label(
        image_bytes, brand=brand, alcohol_content=alcohol_content, expected_warning=warning
    )
    return _render_result(
        request, result, brand, alcohol_content,
        image_src=ocr.to_thumbnail_data_uri(image_bytes),
        ocr_text=result.ocr_text,
        expected_warning=warning,
    )


@app.post("/verify-sample/{key}", response_class=HTMLResponse)
def verify_sample(request: Request, key: str):
    sample = SAMPLES.get(key)
    if sample is None or not sample.path.exists():
        return _render_result(
            request, None, "", "", error=f"Unknown sample '{key}'.", status_code=404
        )
    result = verify_label(
        sample.path.read_bytes(),
        brand=sample.brand,
        alcohol_content=sample.alcohol_content,
        expected_warning=OFFICIAL_GOVERNMENT_WARNING,
    )
    return _render_result(
        request, result, sample.brand, sample.alcohol_content,
        image_src=f"/static/samples/{sample.filename}",
        ocr_text=result.ocr_text,
    )


@app.post("/reverify", response_class=HTMLResponse)
def reverify(
    request: Request,
    brand: str = Form(...),
    alcohol_content: str = Form(...),
    ocr_text: str = Form(""),
    image_src: str = Form(""),
    expected_warning: str = Form(OFFICIAL_GOVERNMENT_WARNING),
    confidence: float = Form(100.0),
):
    """Re-check edited brand/ABV against the carried OCR text — no re-OCR (U4)."""
    warning = expected_warning or OFFICIAL_GOVERNMENT_WARNING
    if not ocr.is_readable(ocr_text):
        result = VerificationResult(readable=False, message=UNREADABLE_MESSAGE)
        return _render_result(
            request, result, brand, alcohol_content, image_src=image_src or None
        )
    result = reverify_text(ocr_text, brand=brand, alcohol_content=alcohol_content,
                           expected_warning=warning, confidence=confidence)
    return _render_result(
        request, result, brand, alcohol_content,
        image_src=image_src or None, ocr_text=ocr_text, expected_warning=warning,
    )


@app.get("/batch", response_class=HTMLResponse)
def batch_form(request: Request):
    return templates.TemplateResponse(
        request, "batch.html", {"cap": batch_mod.BATCH_MAX_LABELS}
    )


@app.post("/batch", response_class=HTMLResponse)
async def batch_run(
    request: Request,
    images: list[UploadFile] = File(...),
    mapping: UploadFile = File(...),
):
    """Verify a batch of labels against a CSV of claimed data (stateless)."""
    uploaded = [((img.filename or ""), await img.read()) for img in images]
    result = batch_mod.run_batch(uploaded, await mapping.read())
    results_csv_b64 = ""
    if result.rows:
        results_csv_b64 = base64.b64encode(
            batch_mod.results_to_csv(result).encode()
        ).decode()
    return templates.TemplateResponse(
        request,
        "batch_results.html",
        {"result": result, "results_csv_b64": results_csv_b64,
         "cap": batch_mod.BATCH_MAX_LABELS},
    )


@app.get("/health")
def health():
    return {"status": "ok"}
