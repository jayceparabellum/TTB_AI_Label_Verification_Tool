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

from app.verify import verify_label as _core_verify_label
from .images import STORE

_UNREADABLE = "No label image is loaded — please upload one first."


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


READ_TOOLS = [verify_label]
ALL_TOOLS = READ_TOOLS          # write/RAG tools appended in later units
