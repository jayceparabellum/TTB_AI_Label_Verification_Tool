"""Agent tools. Each READ tool *wraps* an existing deterministic core function and
returns its result verbatim — the tool is the single source of truth, identical to
what the button UI shows. The LLM never decides pass/fail; it only calls these and
narrates what they return.

Phase A ships one read tool: verify_label. Write tools (override_result, ...) and
RAG tools arrive in later units.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from app import ocr as _ocr
from app import batch as _batch
from app.matching import match_government_warning as _match_warning
from app.samples import SAMPLES as _SAMPLES
from app.verify import reverify_text as _core_reverify_text
from app.verify import verify_label as _core_verify_label
from . import audit
from .images import STORE

_UNREADABLE = "No label image is loaded — please upload one first."
_UNREADABLE_TEXT = "No label text to verify — please paste the label text first."
# Most-recent batch result for list_flagged; populated by batch_verify (slice D).
LAST_BATCH = None


def _serialize(r) -> dict:
    """Serialize a VerificationResult verbatim — the single shape every verify tool
    returns, so image and text verdicts are indistinguishable downstream."""
    return {
        "readable": r.readable,
        "overall_pass": r.overall_pass,
        "needs_review": r.needs_review,
        "confidence": round(r.confidence),
        "elapsed_ms": r.elapsed_ms,
        "fields": [
            {"field": f.field, "label": f.label, "passed": f.passed,
             "expected": f.expected, "found": f.found, "detail": f.detail}
            for f in r.fields
        ],
        "message": r.message,
    }


def run_verify(image_id: str | None, brand: str, alcohol_content: str) -> dict:
    """Deterministic verification, serialized verbatim. Shared by the tool and by
    tests (so the parity assertion needs no InjectedState plumbing)."""
    if not image_id:
        return {"error": _UNREADABLE}
    data = STORE.get(image_id)
    if data is None:
        return {"error": _UNREADABLE}
    r = _core_verify_label(data, brand=brand, alcohol_content=alcohol_content)
    return _serialize(r)


def run_verify_text(label_text: str, brand: str, alcohol_content: str,
                    expected_warning: str = "") -> dict:
    """Deterministic text re-verification, serialized verbatim. Shared by the tool
    and by tests so the parity assertion needs no InjectedState plumbing. The pasted
    text IS the label text (the user supplied it), so there is no OCR step."""
    if not _ocr.is_readable(label_text):
        return {"error": _UNREADABLE_TEXT}
    kwargs = {"expected_warning": expected_warning} if expected_warning else {}
    r = _core_reverify_text(label_text, brand=brand,
                            alcohol_content=alcohol_content, **kwargs)
    return _serialize(r)


def _regulation_for(field: str, detail: str) -> dict | None:
    """Look up the controlling regulation for a FLAGGED field via the RAG corpus.
    Advisory annotation only — it never changes the verdict. Any retrieval failure
    returns None so verification degrades gracefully and RAG can't break the result.
    Runs off the deterministic core path, so it never affects the < 5s verify SLA."""
    from rag import generate
    try:
        g = generate.explain_flag(field, detail or "")
    except Exception:
        return None
    if g.get("status") != "answered":
        return None
    cite = (g.get("citations") or [{}])[0]
    return {"citation": cite.get("citation"), "section": cite.get("section"),
            "explanation": g.get("explanation")}


def _attach_regulations(result: dict) -> dict:
    """Attach the controlling regulation to every FLAGGED field. Deterministic
    pass/fail is untouched; this only adds a grounded, cited explanation."""
    for f in result.get("fields", []):
        if f.get("passed") is False:
            reg = _regulation_for(f["field"], f.get("detail", ""))
            if reg:
                f["regulation"] = reg
    return result


@tool
def verify_label(
    brand: str,
    alcohol_content: str,
    state: Annotated[dict, InjectedState],
) -> dict:
    """Verify the currently-loaded label image against the claimed brand and
    alcohol content. Returns the deterministic per-field PASS/FLAG verdict — this
    is the authoritative result, not your opinion. Any FLAG carries the controlling
    27 CFR regulation (grounded + cited) so you can explain *why* it failed. The
    image is taken from the active session (you do not supply it)."""
    result = run_verify(state.get("active_image_id"), brand, alcohol_content)
    return _attach_regulations(result)


@tool
def verify_text(
    label_text: str,
    brand: str,
    alcohol_content: str,
    expected_warning: str = "",
) -> dict:
    """Verify label TEXT the user pasted or typed (no image) against the claimed
    brand and alcohol content. Use this when the user gives you the label's wording
    directly instead of an image. Returns the deterministic per-field PASS/FLAG
    verdict — this is the authoritative result, not your opinion. Any FLAG carries
    the controlling 27 CFR regulation (grounded + cited) so you can explain why it
    failed. The label_text you pass IS the wording to check, verbatim."""
    result = run_verify_text(label_text, brand, alcohol_content, expected_warning)
    return _attach_regulations(result)


@tool
def override_result(
    result_id: str,
    new_status: str,
    reason: str,
    state: Annotated[dict, InjectedState],
) -> dict:
    """Record a HUMAN's override of a verification result (e.g. mark a flagged
    label PASS after manual review). This is a WRITE action — it only runs after a
    person approves it via the confirm gate, and it is written to the audit log.
    You may PROPOSE an override and explain why, but you never decide it yourself.
    A reason is mandatory."""
    if not reason or not reason.strip():
        return {"error": "An override needs a written reason; none was given."}
    new = new_status.strip().upper()
    if new not in {"PASS", "FLAG"}:
        return {"error": f"new_status must be PASS or FLAG, got {new_status!r}."}
    rid = result_id or state.get("last_result_id") or "unknown"
    row = audit.record(actor="agent-user", action="override", target_result_id=rid,
                       old_verdict=None, new_verdict=new, reason=reason.strip())
    return {"ok": True, "recorded_id": row, "result_id": rid,
            "new_status": new, "reason": reason.strip()}


def _active_image(state: dict) -> bytes | None:
    image_id = state.get("active_image_id")
    return STORE.get(image_id) if image_id else None


@tool
def extract_label_fields(state: Annotated[dict, InjectedState]) -> dict:
    """Read the raw text off the currently-loaded label (best-effort OCR). This is
    NOT a verdict — use verify_label for pass/fail. Useful for showing what the
    scanner saw or spotting an unreadable field."""
    data = _active_image(state)
    if data is None:
        return {"error": _UNREADABLE}
    try:
        text, conf = _ocr.extract_text_data(data)
    except _ocr.OcrReadError as exc:
        return {"error": "Couldn't read this image.", "detail": str(exc)}
    return {"readable": _ocr.is_readable(text), "confidence": round(conf),
            "text": text,
            "note": "best-effort OCR; fields here are not adjudicated"}


@tool
def verify_warning(state: Annotated[dict, InjectedState]) -> dict:
    """Check just the government health warning on the loaded label against 27 CFR
    16.21 (exact wording + ALL-CAPS header). Returns the deterministic result."""
    data = _active_image(state)
    if data is None:
        return {"error": _UNREADABLE}
    try:
        text, _ = _ocr.extract_text_data(data)
    except _ocr.OcrReadError as exc:
        return {"error": "Couldn't read this image.", "detail": str(exc)}
    r = _match_warning(text)
    return {"passed": r.passed, "found": r.found, "detail": r.detail,
            "inconclusive": r.inconclusive}


@tool
def list_flagged() -> dict:
    """List only the flagged rows from the most recent batch run this session."""
    if LAST_BATCH is None:
        return {"flagged": [], "note": "No batch has been run in this session yet."}
    flagged = [r for r in getattr(LAST_BATCH, "rows", []) if getattr(r, "needs_attention", False)]
    return {"count": len(flagged),
            "flagged": [{"filename": r.filename, "status": r.status} for r in flagged]}


@tool
def manual_fallback(
    field: str,
    value: str,
    state: Annotated[dict, InjectedState],
) -> dict:
    """Record a human-typed value for a field OCR could not read (e.g. the agent
    reads the ABV by eye). WRITE action — human-gated and logged as a manual entry.
    Propose it when a field is unreadable; never invent the value yourself."""
    if not value or not value.strip():
        return {"error": "Provide the value you read off the label."}
    rid = state.get("last_result_id") or "current"
    row = audit.record(actor="agent-user", action="manual_entry", target_result_id=rid,
                       old_verdict=None, new_verdict=f"{field}={value.strip()}",
                       reason=f"OCR could not read {field}; human entered '{value.strip()}'")
    return {"ok": True, "field": field, "value": value.strip(), "recorded_id": row}


# --- RAG tools: grounded, cite-or-refuse (Layer 3) ----------------------------
@tool
def regulatory_lookup(question: str, beverage_type: str = "") -> dict:
    """Answer a regulatory question (e.g. 'what does a wine label need?') ONLY from
    the regulations on file, always with a 27 CFR citation. Refuses if the answer
    isn't in the corpus. Never answer regulatory questions from your own memory —
    always call this tool."""
    from rag import generate
    return generate.answer(question, beverage_type or None)


@tool
def explain_flag(field: str, failure_reason: str) -> dict:
    """Attach the controlling regulation (with citation) to a deterministic FLAG —
    e.g. a Title-case warning header maps to the ALL-CAPS rule in 27 CFR 16.22.
    Grounded in the corpus; refuses if no controlling rule is found."""
    from rag import generate
    return generate.explain_flag(field, failure_reason)


@tool
def batch_verify() -> dict:
    """Verify all loaded sample labels at once and summarize the results. Expensive
    action — human-gated. Afterwards, call list_flagged to see only the problems."""
    global LAST_BATCH
    uploaded = [(s.filename, s.path.read_bytes()) for s in _SAMPLES.values()]
    csv = "filename,brand,alcohol_content\n" + "\n".join(
        f"{s.filename},{s.brand},{s.alcohol_content}" for s in _SAMPLES.values())
    LAST_BATCH = _batch.run_batch(uploaded, csv.encode())
    s = LAST_BATCH.summary
    return {"total": s.get("total", 0), "passed": s.get("passed", 0),
            "flagged": s.get("flagged", 0), "needs_review": s.get("needs_review", 0),
            "errors": s.get("errors", 0)}


_KNOWN_WINE_TYPES = {
    "table wine", "red wine", "white wine", "rose wine", "rosé wine",
    "sparkling wine", "dessert wine", "fortified wine",
}


@tool
def validate_class_type(claimed_designation: str, beverage_type: str = "wine") -> dict:
    """Assess a claimed class/type designation against the standards of identity —
    ADVISORY ONLY (status OK or REVIEW), never an automatic rejection. Returns the
    controlling citation; a human decides."""
    from rag import generate

    norm = claimed_designation.strip().lower()
    grounded = generate.explain_flag("class type designation",
                                     f"{beverage_type} {claimed_designation}")
    citations = grounded.get("citations", [])
    if norm in _KNOWN_WINE_TYPES:
        return {"status": "OK", "advisory": True, "citations": citations,
                "assessment": f"'{claimed_designation}' is a recognized class/type."}
    return {"status": "REVIEW", "advisory": True, "citations": citations,
            "assessment": (f"'{claimed_designation}' is not a simple recognized "
                           "class/type — recommend human review against the standards "
                           "of identity. This is advisory; it is never an auto-rejection.")}


READ_TOOLS = [verify_label, verify_text, extract_label_fields, verify_warning,
              list_flagged, regulatory_lookup, explain_flag, validate_class_type]
WRITE_TOOLS = [override_result, manual_fallback, batch_verify]
WRITE_TOOL_NAMES = {t.name for t in WRITE_TOOLS}
ALL_TOOLS = READ_TOOLS + WRITE_TOOLS
