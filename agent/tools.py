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
from app.matching import match_government_warning as _match_warning
from app.verify import verify_label as _core_verify_label
from . import audit
from .images import STORE

_UNREADABLE = "No label image is loaded — please upload one first."
# Most-recent batch result for list_flagged; populated by batch_verify (slice D).
LAST_BATCH = None


def run_verify(image_id: str | None, brand: str, alcohol_content: str) -> dict:
    """Deterministic verification, serialized verbatim. Shared by the tool and by
    tests (so the parity assertion needs no InjectedState plumbing)."""
    if not image_id:
        return {"error": _UNREADABLE}
    data = STORE.get(image_id)
    if data is None:
        return {"error": _UNREADABLE}
    r = _core_verify_label(data, brand=brand, alcohol_content=alcohol_content)
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


@tool
def verify_label(
    brand: str,
    alcohol_content: str,
    state: Annotated[dict, InjectedState],
) -> dict:
    """Verify the currently-loaded label image against the claimed brand and
    alcohol content. Returns the deterministic per-field PASS/FLAG verdict — this
    is the authoritative result, not your opinion. The image is taken from the
    active session (you do not supply it)."""
    return run_verify(state.get("active_image_id"), brand, alcohol_content)


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


# --- RAG tools: STUBS until Phase C (they REFUSE rather than answer from memory) --
_RAG_STUB = ("The citation-grounded regulatory knowledge layer is not built yet "
             "(coming in the next phase). I will not answer regulatory questions "
             "from memory.")


@tool
def regulatory_lookup(question: str, beverage_type: str = "") -> dict:
    """Answer a regulatory question with citations to 27 CFR. (Stub — refuses until
    the RAG layer is built.)"""
    return {"status": "unavailable", "answer": None, "citations": [], "message": _RAG_STUB}


@tool
def explain_flag(field: str, failure_reason: str) -> dict:
    """Attach the controlling regulation to a FLAG, with a citation. (Stub —
    refuses until the RAG layer is built.)"""
    return {"status": "unavailable", "explanation": None, "citations": [], "message": _RAG_STUB}


READ_TOOLS = [verify_label, extract_label_fields, verify_warning, list_flagged,
              regulatory_lookup, explain_flag]
WRITE_TOOLS = [override_result, manual_fallback]
WRITE_TOOL_NAMES = {t.name for t in WRITE_TOOLS}
ALL_TOOLS = READ_TOOLS + WRITE_TOOLS
# Phase C will REPLACE the regulatory_lookup / explain_flag stubs with real RAG.
