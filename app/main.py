"""FastAPI app: one upload screen, one results screen.

Kept deliberately small and server-rendered (Jinja2 + vanilla CSS, no JS build)
so the UI is large-target, obvious, and usable by the least tech-comfortable
agent. Stateless: nothing is persisted; each request is processed and discarded.
"""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
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
            "nav": "single",
            "samples": list(SAMPLES.values()),
            "official_warning": OFFICIAL_GOVERNMENT_WARNING,
        },
    )


@app.get("/text", response_class=HTMLResponse)
def text_form(request: Request):
    return templates.TemplateResponse(
        request, "text.html",
        {"nav": "text", "official_warning": OFFICIAL_GOVERNMENT_WARNING},
    )


# --- Conversational agent (Layer 2, additive to the button UI) ----------------
PROMPT_CHIPS = [
    ("Verify the Clean Pass sample", "clean_pass"),
    ("Verify the Wrong-ABV sample", "abv_mismatch"),
    ("What does a wine label need?", ""),
    ("Verify all the sample labels", ""),
    ("Show only the flagged ones", ""),
]
# Exposed to every template so the global pop-out chat widget (in base.html) can
# render the same chips without each route passing them.
templates.env.globals["prompt_chips"] = PROMPT_CHIPS


@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    return templates.TemplateResponse(
        request, "agent.html", {"nav": "chat", "chips": PROMPT_CHIPS},
    )


_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@app.post("/agent/chat")
def agent_chat(message: str = Form(...), image_id: str = Form(""),
               thread_id: str = Form(...)):
    """Stream one agent turn as SSE. Pauses with a 'confirm' event before any
    write; the client then calls /agent/resume with the same thread_id."""
    from .agent_chat import stream_chat

    return StreamingResponse(
        stream_chat(message, image_id or None, thread_id),
        media_type="text/event-stream", headers=_SSE_HEADERS,
    )


@app.post("/agent/resume")
def agent_resume(thread_id: str = Form(...), decision: str = Form(...)):
    """Resume a paused run after the human approved/cancelled the proposed write."""
    from .agent_chat import resume_chat

    return StreamingResponse(
        resume_chat(thread_id, decision),
        media_type="text/event-stream", headers=_SSE_HEADERS,
    )


# In-chat upload: stash an uploaded label image in the session so the assistant can
# verify it (not just the seeded samples). Bytes live in-process only (no disk, no
# PII); the chat then references the returned id. Caps keep a public demo bounded.
_MAX_FILE_BYTES = 10 * 1024 * 1024          # 10 MB per file
_MAX_THREAD_BYTES = 50 * 1024 * 1024        # 50 MB cumulative per chat thread
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff")


def _thread_bytes(thread_id: str) -> int:
    from agent.images import STORE, STAGING
    ids = (STAGING._by_thread.get(thread_id) or {}).get("image_ids", [])
    return sum(len(STORE.get(i) or b"") for i in ids)


@app.post("/agent/upload")
async def agent_upload(thread_id: str = Form(...), files: list[UploadFile] = File(...)):
    """Accept files dropped/picked in the chat. Images are stashed for verification;
    other types get a friendly rejection. Returns one item per file."""
    from agent.images import STORE, STAGING

    items = []
    used = _thread_bytes(thread_id)
    for f in files:
        data = await f.read()
        name = f.filename or "file"
        ct = (f.content_type or "").lower()
        lname = name.lower()
        if len(data) > _MAX_FILE_BYTES:
            items.append({"kind": "rejected", "name": name,
                          "reason": "too large — 10 MB max per file"})
            continue
        if used + len(data) > _MAX_THREAD_BYTES:
            items.append({"kind": "rejected", "name": name,
                          "reason": "this chat has reached its 50 MB upload limit"})
            continue
        if ct.startswith("image/") or lname.endswith(_IMAGE_EXTS):
            image_id = STORE.put(data)
            STAGING.add_image(thread_id, image_id)
            used += len(data)
            items.append({"kind": "image", "id": image_id, "name": name})
        elif ct in ("text/csv", "application/vnd.ms-excel") or lname.endswith(".csv"):
            items.append({"kind": "rejected", "name": name,
                          "reason": "CSV batch in chat is coming soon — use the Batch "
                                    "page for now"})
        else:
            items.append({"kind": "rejected", "name": name,
                          "reason": "unsupported file — images only for now"})
    return JSONResponse({"items": items})


@app.post("/agent/reset")
def agent_reset(thread_id: str = Form(...)):
    """Evict everything a chat thread staged (called when the user closes/clears it)."""
    from agent.images import STAGING
    STAGING.clear(thread_id)
    return JSONResponse({"ok": True})


@app.post("/verify-text", response_class=HTMLResponse)
def verify_text(
    request: Request,
    label_text: str = Form(...),
    brand: str = Form(...),
    alcohol_content: str = Form(...),
    expected_warning: str = Form(OFFICIAL_GOVERNMENT_WARNING),
):
    """Verify typed/pasted label text against the claimed data (no image, no OCR)."""
    text = label_text.strip()
    warning = expected_warning or OFFICIAL_GOVERNMENT_WARNING
    if not ocr.is_readable(text):
        result = VerificationResult(
            readable=False,
            message="Please paste the label text (brand, alcohol content, and the "
                    "government warning) so we have something to check.",
        )
        return _render_result(request, result, brand, alcohol_content)
    # The typed text IS the label text; run the matchers directly (high confidence).
    result = reverify_text(text, brand=brand, alcohol_content=alcohol_content,
                           expected_warning=warning)
    return _render_result(
        request, result, brand, alcohol_content,
        ocr_text=text, expected_warning=warning,
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
        request, "batch.html", {"nav": "batch", "cap": batch_mod.BATCH_MAX_LABELS}
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
        {"nav": "batch", "wide": True, "result": result,
         "results_csv_b64": results_csv_b64, "cap": batch_mod.BATCH_MAX_LABELS},
    )


@app.get("/health")
def health():
    return {"status": "ok"}
