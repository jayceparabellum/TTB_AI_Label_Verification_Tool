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

import logging
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from .reference import OFFICIAL_GOVERNMENT_WARNING, WARNING_HEADER

logger = logging.getLogger(__name__)

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
    candidates.append(ocr_text.strip())

    # partial_ratio finds a brand embedded in a longer line, but for a short
    # brand it matches incidental substrings of the whole page (e.g. "Bud"
    # against any "...bud..."), so only use it once the brand is long enough
    # to be discriminating. Short brands must match a line closely (ratio).
    use_partial = len(exp_norm.replace(" ", "")) >= 5

    for line in candidates:
        line_norm = normalize_loose(line)
        if not line_norm or not exp_norm:
            continue
        score = fuzz.ratio(exp_norm, line_norm)
        if use_partial:
            score = max(score, fuzz.partial_ratio(exp_norm, line_norm))
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
# An alcohol keyword within this many characters of a percentage marks it as an
# alcohol statement (vs. e.g. "5% real juice", "100% recycled").
_ALC_KEYWORDS = ("alc", "abv", "vol")
_ALC_WINDOW = 12


def _parse_claimed_abv(expected: str):
    """Pull a single numeric ABV out of the claimed value ('5', '5.0%', etc.)."""
    m = re.search(r"\d+(?:\.\d+)?", expected)
    return float(m.group()) if m else None


def _abv_candidates(ocr_text: str) -> list[tuple[float, str]]:
    """Extract (abv_value, display_label) pairs that look like alcohol content.

    Prefers numbers in *alcohol context* — a percentage next to ALC/ABV/VOL, an
    explicit "ALC <n>", or a proof value — so unrelated percentages on the label
    ("5% real juice") don't get treated as the alcohol content. Falls back to
    bare percentages only when no alcohol-context number is present at all.
    """
    low = ocr_text.lower()
    out: list[tuple[float, str]] = []

    for m in _PERCENT_RE.finditer(ocr_text):
        window = low[max(0, m.start() - _ALC_WINDOW): m.end() + _ALC_WINDOW]
        if any(k in window for k in _ALC_KEYWORDS):
            v = float(m.group(1))
            out.append((v, f"{v:g}%"))
    for m in _ALC_NUM_RE.finditer(ocr_text):
        v = float(m.group(1))
        out.append((v, f"{v:g}% (ALC)"))
    for m in _PROOF_RE.finditer(ocr_text):
        v = float(m.group(1)) / 2.0
        out.append((v, f"{m.group(1)} proof (= {v:g}% ABV)"))

    if not out:  # best-effort fallback: any percentage on the label
        for m in _PERCENT_RE.finditer(ocr_text):
            v = float(m.group(1))
            out.append((v, f"{v:g}%"))

    # Dedupe by value, keeping the first (most specific) label.
    seen: set[float] = set()
    deduped: list[tuple[float, str]] = []
    for v, label in out:
        if v not in seen:
            seen.add(v)
            deduped.append((v, label))
    return deduped


def match_alcohol_content(expected: str, ocr_text: str) -> FieldResult:
    """Numeric ABV match. Understands '%', 'ALC/VOL', and proof (= 2 x ABV)."""
    claimed = _parse_claimed_abv(expected)
    candidates = _abv_candidates(ocr_text)

    if claimed is None:
        logger.warning(
            "Could not parse a numeric ABV from claimed value: %r", expected
        )
        return FieldResult(
            field="alcohol_content",
            label="Alcohol content",
            passed=False,
            expected=expected,
            found="(unable to compare)",
            detail=f"could not parse a numeric ABV from the claimed value '{expected}'",
        )

    matched = None
    for value, label in candidates:
        if abs(value - claimed) <= ABV_TOLERANCE:
            matched = (value, label)
            break

    passed = matched is not None
    if passed:
        found_display = matched[1]
        detail = "matches the claimed alcohol content"
    elif candidates:
        found_display = ", ".join(label for _, label in candidates)
        detail = "label alcohol content differs from the application"
    else:
        found_display = "(no alcohol content found on label)"
        detail = "no alcohol statement detected on the label"

    return FieldResult(
        field="alcohol_content",
        label="Alcohol content",
        passed=passed,
        expected=f"{claimed:g}% ABV",
        found=found_display,
        detail=detail,
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
