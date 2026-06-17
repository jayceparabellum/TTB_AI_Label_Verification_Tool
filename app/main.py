"""FastAPI app: one upload screen, one results screen.

Kept deliberately small and server-rendered (Jinja2 + vanilla CSS, no JS build)
so the UI is large-target, obvious, and usable by the least tech-comfortable
agent. Stateless: nothing is persisted; each request is processed and discarded.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .reference import OFFICIAL_GOVERNMENT_WARNING
from .samples import SAMPLES
from .verify import verify_label

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent

app = FastAPI(title="TTB Label Verification", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "samples": list(SAMPLES.values()),
            "official_warning": OFFICIAL_GOVERNMENT_WARNING,
        },
    )


def _render_result(request: Request, result, brand: str, alcohol_content: str):
    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "result": result,
            "brand": brand,
            "alcohol_content": alcohol_content,
        },
    )


@app.post("/verify", response_class=HTMLResponse)
async def verify(
    request: Request,
    label_image: UploadFile = File(...),
    brand: str = Form(...),
    alcohol_content: str = Form(...),
    expected_warning: str = Form(OFFICIAL_GOVERNMENT_WARNING),
):
    try:
        image_bytes = await label_image.read()
    except Exception as exc:
        logger.error("Failed to read uploaded file: %s", exc)
        return templates.TemplateResponse(
            "results.html",
            {
                "request": request,
                "result": None,
                "error": "Failed to read the uploaded file. Please try again.",
                "brand": brand,
                "alcohol_content": alcohol_content,
            },
            status_code=400,
        )

    if not image_bytes:
        return templates.TemplateResponse(
            "results.html",
            {
                "request": request,
                "result": None,
                "error": "No image data received. Please select a file and try again.",
                "brand": brand,
                "alcohol_content": alcohol_content,
            },
            status_code=400,
        )

    try:
        result = verify_label(
            image_bytes,
            brand=brand,
            alcohol_content=alcohol_content,
            expected_warning=expected_warning or OFFICIAL_GOVERNMENT_WARNING,
        )
    except Exception as exc:
        logger.exception("Unexpected error during label verification")
        return templates.TemplateResponse(
            "results.html",
            {
                "request": request,
                "result": None,
                "error": f"An internal error occurred during verification: {exc}",
                "brand": brand,
                "alcohol_content": alcohol_content,
            },
            status_code=500,
        )

    return _render_result(request, result, brand, alcohol_content)


@app.post("/verify-sample/{key}", response_class=HTMLResponse)
def verify_sample(request: Request, key: str):
    sample = SAMPLES.get(key)
    if sample is None:
        logger.warning("Sample verification requested for unknown key: %r", key)
        return templates.TemplateResponse(
            "results.html",
            {
                "request": request,
                "result": None,
                "error": f"Unknown sample '{key}'.",
                "brand": "",
                "alcohol_content": "",
            },
            status_code=404,
        )

    if not sample.path.exists():
        logger.error(
            "Sample image missing from disk: %s (run scripts/generate_samples.py)",
            sample.path,
        )
        return templates.TemplateResponse(
            "results.html",
            {
                "request": request,
                "result": None,
                "error": (
                    f"Sample image '{sample.filename}' not found on disk. "
                    "Run scripts/generate_samples.py to regenerate samples."
                ),
                "brand": sample.brand,
                "alcohol_content": sample.alcohol_content,
            },
            status_code=500,
        )

    try:
        result = verify_label(
            sample.path.read_bytes(),
            brand=sample.brand,
            alcohol_content=sample.alcohol_content,
            expected_warning=OFFICIAL_GOVERNMENT_WARNING,
        )
    except Exception as exc:
        logger.exception("Unexpected error verifying sample '%s'", key)
        return templates.TemplateResponse(
            "results.html",
            {
                "request": request,
                "result": None,
                "error": f"An internal error occurred during verification: {exc}",
                "brand": sample.brand,
                "alcohol_content": sample.alcohol_content,
            },
            status_code=500,
        )

    return _render_result(request, result, sample.brand, sample.alcohol_content)


@app.get("/health")
def health():
    return {"status": "ok"}
