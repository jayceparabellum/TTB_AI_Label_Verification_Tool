"""FastAPI app: one upload screen, one results screen.

Kept deliberately small and server-rendered (Jinja2 + vanilla CSS, no JS build)
so the UI is large-target, obvious, and usable by the least tech-comfortable
agent. Stateless: nothing is persisted; each request is processed and discarded.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

_log = logging.getLogger(__name__)

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import batch as batch_mod
from . import ingest
from . import reasons as reasons_mod
from . import ocr
from .models import VerificationResult
from .reference import OFFICIAL_GOVERNMENT_WARNING
from .samples import SAMPLES
from .verify import UNREADABLE_MESSAGE, reverify_text, verify_label

BASE_DIR = Path(__file__).parent

app = FastAPI(title="TTB Label Verification", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Security response headers on every response. CSP is tuned to what this app uses:
# scripts only from our own origin (no inline JS — the print button uses a listener,
# not onclick); inline styles are allowed (a few trivial style= attributes, low risk);
# images allow data: URIs (label thumbnails). object/base/frame-ancestors locked down.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"),
}


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


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
# Detailed per-flag reason explanations, callable from result templates.
templates.env.globals["flag_reason"] = reasons_mod.explain


@app.get("/chat", response_class=HTMLResponse)
@app.get("/assistant", response_class=HTMLResponse)  # alias for /chat
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
_MAX_FILE_BYTES = ingest.MAX_FILE_BYTES     # 10 MB per file (canonical in app/ingest)
_MAX_THREAD_BYTES = 50 * 1024 * 1024        # 50 MB cumulative per chat thread (distinct concept)
_IMAGE_EXTS = ingest.IMAGE_EXTS             # shared accepted-image extensions


def _thread_bytes(thread_id: str) -> int:
    """Cumulative bytes a thread has staged — uploaded images plus the batch CSV —
    so the per-thread cap reflects everything held in memory for this chat."""
    from agent.images import STORE, STAGING
    entry = STAGING._by_thread.get(thread_id) or {}
    image_bytes = sum(len(STORE.get(i) or b"") for i in entry.get("image_ids", []))
    return image_bytes + len(entry.get("batch_csv") or b"")


def _stage_image(thread_id: str, name: str, data: bytes) -> str:
    """Stash one image in the session and stage it as a batch candidate (by its
    original filename, so a CSV batch can match it). Returns the image id. Shared by
    the loose-image and unzipped-image upload paths so they can't drift."""
    from agent.images import STORE, STAGING
    image_id = STORE.put(data)
    STAGING.add_image(thread_id, image_id)
    STAGING.add_batch_image(thread_id, name, data)
    return image_id


@app.post("/agent/upload")
async def agent_upload(thread_id: str = Form(...), files: list[UploadFile] = File(...)):
    """Accept files dropped/picked in the chat. Images are stashed for verification;
    other types get a friendly rejection. Returns one item per file."""
    from agent.images import STAGING

    items = []
    used = _thread_bytes(thread_id)
    for f in files:
        data = await f.read()
        name = f.filename or "file"
        ct = (f.content_type or "").lower()
        lname = name.lower()
        if _is_zip(name, ct):
            # A .zip is a container — unzip it and stage every image, so a zipped
            # folder and loose images take the same batch path. The per-file cap
            # doesn't apply to the archive; ingest enforces per-member + total
            # size guards, and the thread cap applies to the extracted total.
            try:
                extracted = ingest.extract_images_from_zip(data)
            except ingest.ZipIngestError as exc:
                items.append({"kind": "rejected", "name": name, "reason": str(exc)})
                continue
            total = sum(len(b) for _, b in extracted)
            if used + total > _MAX_THREAD_BYTES:
                items.append({"kind": "rejected", "name": name,
                              "reason": "this chat has reached its 50 MB upload limit"})
                continue
            for img_name, img_bytes in extracted:
                _stage_image(thread_id, img_name, img_bytes)
            used += total
            items.append({"kind": "zip", "name": name, "extracted": len(extracted)})
            continue
        if len(data) > _MAX_FILE_BYTES:
            items.append({"kind": "rejected", "name": name,
                          "reason": "too large — 10 MB max per file"})
            continue
        if used + len(data) > _MAX_THREAD_BYTES:
            items.append({"kind": "rejected", "name": name,
                          "reason": "this chat has reached its 50 MB upload limit"})
            continue
        if ct.startswith("image/") or lname.endswith(_IMAGE_EXTS):
            image_id = _stage_image(thread_id, name, data)
            used += len(data)
            items.append({"kind": "image", "id": image_id, "name": name})
        elif ct in ("text/csv", "application/vnd.ms-excel") or lname.endswith(".csv"):
            try:
                rows, _dups = batch_mod.parse_csv(data)   # validate before staging
            except batch_mod.CsvFormatError as exc:
                items.append({"kind": "rejected", "name": name, "reason": str(exc)})
                continue
            STAGING.set_batch_csv(thread_id, data)
            used += len(data)
            items.append({"kind": "csv", "name": name, "rows": len(rows)})
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
    net_contents: str = Form(""),
    class_type: str = Form(""),
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
        return _render_result(request, result, brand, alcohol_content,
                              net_contents=net_contents, class_type=class_type)
    # The typed text IS the label text; run the matchers directly (high confidence).
    result = reverify_text(text, brand=brand, alcohol_content=alcohol_content,
                           expected_warning=warning, net_contents=net_contents,
                           class_type=class_type)
    return _render_result(
        request, result, brand, alcohol_content,
        ocr_text=text, expected_warning=warning,
        net_contents=net_contents, class_type=class_type,
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
    net_contents: str = "",
    class_type: str = "",
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
            "net_contents": net_contents,    # optional adjudicated fields — carried
            "class_type": class_type,        # back for repopulation + re-check
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
    net_contents: str = Form(""),
    class_type: str = Form(""),
):
    # Carried back to repopulate the form on every render (success or error).
    optional = {"net_contents": net_contents, "class_type": class_type}
    # Read at most one byte past the cap so an oversized upload can't exhaust memory.
    image_bytes = await label_image.read(_MAX_FILE_BYTES + 1)
    if len(image_bytes) > _MAX_FILE_BYTES:
        return _render_result(
            request, None, brand, alcohol_content, **optional,
            error="That image is larger than the 10 MB limit. Please upload a smaller file.",
            status_code=413)
    if not image_bytes:
        return _render_result(
            request, None, brand, alcohol_content, **optional,
            error="No image was uploaded — please choose a label image and try again.",
            status_code=400)
    warning = expected_warning or OFFICIAL_GOVERNMENT_WARNING
    try:
        result = verify_label(
            image_bytes, brand=brand, alcohol_content=alcohol_content,
            expected_warning=warning, net_contents=net_contents, class_type=class_type,
        )
    except Exception:  # noqa: BLE001 — surface a clear error page, not an unhandled 500
        _log.exception("verify_label failed for a /verify upload (%d bytes)", len(image_bytes))
        return _render_result(
            request, None, brand, alcohol_content, **optional,
            error="Something went wrong verifying this label. Please try again; if it "
                  "persists, check the server logs.",
            status_code=500)
    return _render_result(
        request, result, brand, alcohol_content, **optional,
        image_src=ocr.to_thumbnail_data_uri(image_bytes),
        ocr_text=result.ocr_text,
        expected_warning=warning,
    )


@app.post("/verify-sample/{key}", response_class=HTMLResponse)
def verify_sample(request: Request, key: str):
    sample = SAMPLES.get(key)
    if sample is None:
        return _render_result(
            request, None, "", "", error=f"Unknown sample '{key}'.", status_code=404
        )
    if not sample.path.exists():
        _log.error("sample '%s' is configured but its image is missing: %s", key, sample.path)
        return _render_result(
            request, None, "", "",
            error=f"Sample '{key}' is configured but its image is missing on the server. "
                  "Run scripts/generate_samples.py to regenerate the bundled samples.",
            status_code=500)
    try:
        result = verify_label(
            sample.path.read_bytes(),
            brand=sample.brand,
            alcohol_content=sample.alcohol_content,
            expected_warning=OFFICIAL_GOVERNMENT_WARNING,
        )
    except Exception:  # noqa: BLE001
        _log.exception("verify_label failed for sample '%s'", key)
        return _render_result(
            request, None, sample.brand, sample.alcohol_content,
            error="Something went wrong verifying this sample. Please check the server logs.",
            status_code=500)
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
    net_contents: str = Form(""),
    class_type: str = Form(""),
):
    """Re-check edited claimed data against the carried OCR text — no re-OCR (U4)."""
    warning = expected_warning or OFFICIAL_GOVERNMENT_WARNING
    optional = {"net_contents": net_contents, "class_type": class_type}
    if not ocr.is_readable(ocr_text):
        result = VerificationResult(readable=False, message=UNREADABLE_MESSAGE)
        return _render_result(
            request, result, brand, alcohol_content, image_src=image_src or None, **optional
        )
    result = reverify_text(ocr_text, brand=brand, alcohol_content=alcohol_content,
                           expected_warning=warning, confidence=confidence,
                           net_contents=net_contents, class_type=class_type)
    return _render_result(
        request, result, brand, alcohol_content,
        image_src=image_src or None, ocr_text=ocr_text, expected_warning=warning, **optional,
    )


@app.get("/batch", response_class=HTMLResponse)
def batch_form(request: Request):
    return templates.TemplateResponse(
        request, "batch.html", {"nav": "batch", "cap": batch_mod.BATCH_MAX_LABELS}
    )


def _is_zip(name: str, content_type: str) -> bool:
    return name.lower().endswith(".zip") or content_type in (
        "application/zip", "application/x-zip-compressed", "application/x-zip")


async def _expand_uploads(uploads: list[UploadFile]) -> list[tuple[str, bytes]]:
    """Read uploads into (filename, bytes), expanding any .zip into its image
    members so a zipped folder, a picked folder (webkitdirectory), and loose images
    all take the same downstream path. Non-image, non-zip entries (folder junk like
    .DS_Store, Thumbs.db, or nested metadata) are skipped rather than fed to the
    verifier. Raises ingest.ZipIngestError on a corrupt or over-cap archive."""
    out: list[tuple[str, bytes]] = []
    for up in uploads:
        name = up.filename or ""
        ct = (up.content_type or "").lower()
        if _is_zip(name, ct):
            out.extend(ingest.extract_images_from_zip(await up.read()))
        elif ct.startswith("image/") or name.lower().endswith(_IMAGE_EXTS):
            # Use the basename: a picked folder sends "folder/sub/label.png" as the
            # filename, which must still match the CSV's "label.png" row.
            base = name.replace("\\", "/").rsplit("/", 1)[-1]
            out.append((base, await up.read()))
        # else: skip — not an image or zip (folder junk / unsupported file).
    return out


@app.post("/batch", response_class=HTMLResponse)
async def batch_run(
    request: Request,
    images: list[UploadFile] = File(...),
    mapping: UploadFile = File(...),
):
    """Verify a batch of labels against a CSV of claimed data (stateless). The
    images field accepts loose image files and/or a .zip of label photos."""
    try:
        uploaded = await _expand_uploads(images)
    except ingest.ZipIngestError as exc:
        result = batch_mod.BatchResult(error=str(exc))
    else:
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
