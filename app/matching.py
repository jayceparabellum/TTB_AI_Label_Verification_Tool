"""Field matching logic.

Two deliberately different strategies (this is the heart of the tool):

* Brand name + alcohol content -> FUZZY / tolerant. Formatting, case,
  punctuation, and whitespace differences are NOT mismatches. ABV is compared
  as a number (with proof = 2 x ABV understood), not as a string.
* Government warning -> STRICT. Exact wording, exact casing, the literal
  all-caps "GOVERNMENT WARNING:". Only whitespace (which OCR mangles via line
  wrapping) is normalized. Title-case or altered wording fails.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from .reference import OFFICIAL_GOVERNMENT_WARNING, WARNING_HEADER

# --- Tunables (see PRD-v1.md) -------------------------------------------------
# Brand similarity is measured AFTER normalization (case/punct/whitespace
# stripped), so trivial formatting differences already score 100. The cutoff
# therefore only governs residual OCR noise.
BRAND_SIMILARITY_THRESHOLD = 95.0
# Alcohol content is "exact after normalize": 5 == 5.0 == 5.00, but 5.0 != 5.1.
# A small epsilon absorbs float representation only, not real differences.
ABV_TOLERANCE = 0.05


@dataclass
class FieldResult:
    """Outcome of verifying one field against the label."""

    field: str          # "brand" | "alcohol_content" | "government_warning"
    label: str          # human-friendly field name for the UI
    passed: bool
    expected: str
    found: str
    detail: str = ""


# --- Normalization helpers ----------------------------------------------------
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_loose(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace. For fuzzy comparison."""
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def normalize_whitespace(text: str) -> str:
    """Collapse all whitespace runs to single spaces. Preserves case + wording."""
    return _WS_RE.sub(" ", text).strip()


# --- Brand --------------------------------------------------------------------
def match_brand(expected: str, ocr_text: str) -> FieldResult:
    """Fuzzy brand match. Tolerant of case/punctuation/whitespace formatting."""
    exp_norm = normalize_loose(expected)
    best_line, best_score = "", 0.0

    candidates = [ln.strip() for ln in ocr_text.splitlines() if ln.strip()]
    # Also consider the whole text as one candidate (handles single-line OCR).
    candidates.append(ocr_text)

    for line in candidates:
        line_norm = normalize_loose(line)
        if not line_norm or not exp_norm:
            continue
        # ratio catches whole-string equality; partial_ratio finds the brand
        # embedded in a longer line (e.g. "STONE'S THROW BREWING CO").
        score = max(fuzz.ratio(exp_norm, line_norm),
                    fuzz.partial_ratio(exp_norm, line_norm))
        if score > best_score:
            best_score, best_line = score, line.strip()

    passed = best_score >= BRAND_SIMILARITY_THRESHOLD
    return FieldResult(
        field="brand",
        label="Brand name",
        passed=passed,
        expected=expected,
        found=best_line or "(not found on label)",
        detail=f"similarity {best_score:.0f}/100 (threshold {BRAND_SIMILARITY_THRESHOLD:.0f})",
    )


# --- Alcohol content ----------------------------------------------------------
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_ALC_NUM_RE = re.compile(r"(?:alc(?:ohol)?\.?(?:\s*/?\s*vol)?\.?\s*)(\d+(?:\.\d+)?)", re.I)
_PROOF_RE = re.compile(r"(\d+(?:\.\d+)?)\s*proof", re.I)


def _parse_claimed_abv(expected: str):
    """Pull a single numeric ABV out of the claimed value ('5', '5.0%', etc.)."""
    m = re.search(r"\d+(?:\.\d+)?", expected)
    return float(m.group()) if m else None


def match_alcohol_content(expected: str, ocr_text: str) -> FieldResult:
    """Numeric ABV match. Understands '%', 'ALC/VOL', and proof (= 2 x ABV)."""
    claimed = _parse_claimed_abv(expected)

    pct_vals = [float(x) for x in _PERCENT_RE.findall(ocr_text)]
    alc_vals = [float(x) for x in _ALC_NUM_RE.findall(ocr_text)]
    proof_vals = [float(x) / 2.0 for x in _PROOF_RE.findall(ocr_text)]
    candidates = pct_vals + alc_vals + proof_vals

    found_display = "(no alcohol content found on label)"
    if pct_vals or alc_vals:
        found_display = ", ".join(f"{v:g}%" for v in sorted(set(pct_vals + alc_vals)))
    elif proof_vals:
        found_display = ", ".join(f"{v * 2:g} proof (= {v:g}% ABV)" for v in proof_vals)

    passed = (
        claimed is not None
        and any(abs(c - claimed) <= ABV_TOLERANCE for c in candidates)
    )
    return FieldResult(
        field="alcohol_content",
        label="Alcohol content",
        passed=passed,
        expected=f"{claimed:g}% ABV" if claimed is not None else expected,
        found=found_display,
        detail="proof converted to ABV where applicable",
    )


# --- Government warning (strict) ----------------------------------------------
def match_government_warning(ocr_text: str, expected: str = OFFICIAL_GOVERNMENT_WARNING) -> FieldResult:
    """Strict warning match: exact wording + casing, only whitespace tolerated."""
    norm_ocr = normalize_whitespace(ocr_text)
    norm_expected = normalize_whitespace(expected)

    has_header = WARNING_HEADER in norm_ocr            # case-sensitive, all caps
    has_full_text = norm_expected in norm_ocr          # case-sensitive, exact wording
    passed = has_header and has_full_text

    if passed:
        found = "Exact official warning present (correct wording and ALL CAPS)."
        detail = "matches 27 CFR 16.21 verbatim"
    else:
        # Surface WHY it failed, to make the verdict trustworthy and actionable.
        lower_ocr = norm_ocr.lower()
        if WARNING_HEADER.lower() not in lower_ocr:
            found = "No government warning text detected on the label."
            detail = "missing 'GOVERNMENT WARNING:'"
        elif not has_header:
            found = "Warning present but header is not in required ALL CAPS."
            detail = "expected literal 'GOVERNMENT WARNING:' (all caps)"
        else:
            found = "Header present, but wording does not match the official text."
            detail = "wording differs from 27 CFR 16.21"

    return FieldResult(
        field="government_warning",
        label="Government warning",
        passed=passed,
        expected=expected,
        found=found,
        detail=detail,
    )
