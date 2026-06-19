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
# Government warning: how closely the OCR'd warning body must match the official
# 27 CFR 16.21 text.
#
# Two thresholds form a confidence BAND so a compliant-but-noisy warning is
# DEFERRED to a human (NEEDS REVIEW) instead of confidently FLAGged — the dominant
# false-positive on real labels (Six Sigma verification, 2026-06-19):
#   * body similarity >= PASS  AND ALL-CAPS header present -> PASS
#   * REVIEW_FLOOR <= body < PASS (or a garbled header)    -> NEEDS REVIEW (defer)
#   * body < REVIEW_FLOOR                                   -> FLAG (wording genuinely differs)
# A defer can never become a wrong PASS, so this only ever converts a
# (possibly-false) confident FLAG into a safe human review.
#
# NOTE: REVIEW_FLOOR is provisional — calibrate it against the real-clean-label
# eval slice (eval/images/real_clean/) once that data exists; today it is set low
# so genuinely-compliant-but-noisy reads land in REVIEW, not FLAG.
WARNING_SIMILARITY_THRESHOLD = 99.0     # PASS at/above this (compliant reads score >=99.6%)
WARNING_REVIEW_FLOOR = 85.0             # below this, body wording is genuinely wrong -> FLAG
# How closely the detected header region must match "GOVERNMENT WARNING:" (any case)
# to treat a non-ALL-CAPS header as a *deliberate* Title-case violation (a crisp FLAG)
# rather than OCR noise on the header (defer to REVIEW).
WARNING_HEADER_MATCH_THRESHOLD = 90.0


@dataclass
class FieldResult:
    """Outcome of verifying one field against the label."""

    field: str          # "brand" | "alcohol_content" | "government_warning"
    label: str          # human-friendly field name for the UI
    passed: bool
    expected: str
    found: str
    detail: str = ""
    # True when the field could not be assessed (the region didn't OCR), as
    # opposed to a confident pass/fail. Drives NEEDS REVIEW so the system never
    # confidently FLAGs something it couldn't actually read.
    inconclusive: bool = False


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
    exp_len = len(exp_norm.replace(" ", ""))
    best_line, best_score = "", 0.0

    candidates = [ln.strip() for ln in ocr_text.splitlines() if ln.strip()]
    # Also consider the whole text as one candidate (handles single-line OCR).
    candidates.append(ocr_text.strip())

    # partial_ratio finds a brand embedded in a *longer* line, but it scores by
    # fitting the shorter string inside the longer one — so two failure modes:
    #   1. For a short brand it matches incidental substrings of a busy page
    #      ("Bud" inside "...Brewing..."), so require the brand be discriminating.
    #   2. For ANY brand, a candidate SHORTER than the brand gets found *inside*
    #      the brand and scores 100 — e.g. garbled OCR "i" matches the 'i' in
    #      "danIel", falsely passing "Jack Daniel's". So only use partial_ratio
    #      when the candidate is at least as long as the brand.
    # In every other case a close plain ratio is required, which scores noise low.
    brand_is_discriminating = exp_len >= 5

    for line in candidates:
        line_norm = normalize_loose(line)
        if not line_norm or not exp_norm:
            continue
        score = fuzz.ratio(exp_norm, line_norm)
        if brand_is_discriminating and len(line_norm.replace(" ", "")) >= exp_len:
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
    if claimed is None:
        # The CLAIMED value (application input), not the label, has no parseable
        # number — say so explicitly instead of the misleading "no alcohol on label".
        return FieldResult(
            field="alcohol_content", label="Alcohol content", passed=False,
            expected=expected or "(none)",
            found="(claimed alcohol content not understood)",
            detail=f"could not parse a numeric ABV from the claimed value '{expected}'")
    candidates = _abv_candidates(ocr_text)

    matched = None
    if claimed is not None:
        for value, label in candidates:
            if abs(value - claimed) <= ABV_TOLERANCE:
                matched = (value, label)
                break

    passed = matched is not None
    if passed:
        found_display = matched[1]                 # the value that actually matched
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
        expected=f"{claimed:g}% ABV" if claimed is not None else expected,
        found=found_display,
        detail=detail,
    )


# --- Government warning (strict on wording/casing, tolerant of OCR noise) ------
def _warning_window(norm_ocr: str, norm_expected: str) -> str | None:
    """Slice the OCR text from the warning header to ~1.2x the official length.

    Comparing the official warning against the *whole page* dilutes the score
    with unrelated label text; comparing via partial_ratio matches any substring
    (so a half-printed warning scores 100). Anchoring on the header and bounding
    the window isolates the warning so a plain ratio is meaningful."""
    idx = norm_ocr.lower().find(WARNING_HEADER.lower())
    if idx < 0:
        return None
    return norm_ocr[idx: idx + int(len(norm_expected) * 1.2)]


def _all_official_words_present(window: str, norm_expected: str,
                                min_word_ratio: float = 80.0) -> bool:
    """True only if every word of the official warning has a close match in the OCR
    window. Character-level fuzz.ratio alone can't catch a DROPPED short word — e.g.
    removing 'not' from 'should not drink' still scores ~99% — which would confidently
    PASS a meaning-inverted, non-compliant warning (the worst error). OCR noise
    substitutes characters *within* words (so each word still matches fuzzily) but
    does not delete whole words, so a missing word signals genuine alteration."""
    win_words = normalize_loose(window).split()
    # Only check words of length >= 3: 1-2 char words ('a', 'of', '1') fuzzy-match
    # unreliably and OCR rarely drops them meaningfully, whereas the meaning-bearing
    # words that invert compliance ('not', 'risk', 'pregnancy') are all >= 3 chars.
    for word in normalize_loose(norm_expected).split():
        if len(word) < 3:
            continue
        if not any(fuzz.ratio(word, w) >= min_word_ratio for w in win_words):
            return False
    return True


def match_government_warning(ocr_text: str, expected: str = OFFICIAL_GOVERNMENT_WARNING) -> FieldResult:
    """Verify the government warning: strict on wording + ALL-CAPS casing, but
    tolerant of OCR noise, and DEFERRING (not flagging) when it can't be read.

    Three outcomes:
      * PASS  — ALL-CAPS header present and the body matches the official text
                above the fuzzy threshold (a few characters of OCR noise are OK).
      * FLAG  — the warning is readable but genuinely wrong: header not in ALL
                CAPS (Title case) or wording differs beyond the threshold.
      * REVIEW (inconclusive) — the warning region didn't OCR at all (header not
                found even case-insensitively); we can't assess it, so defer to a
                human instead of confidently FLAGging a possibly-compliant label.
    """
    norm_ocr = normalize_whitespace(ocr_text)
    norm_expected = normalize_whitespace(expected)
    window = _warning_window(norm_ocr, norm_expected)

    def _review(found: str, detail: str) -> FieldResult:
        # Present-but-uncertain -> defer to a human. Never a confident FLAG, never PASS.
        return FieldResult(
            field="government_warning", label="Government warning", passed=False,
            expected=expected, found=found, detail=detail, inconclusive=True)

    def _flag(found: str, detail: str) -> FieldResult:
        return FieldResult(
            field="government_warning", label="Government warning", passed=False,
            expected=expected, found=found, detail=detail)

    # Region didn't OCR at all (header not found even case-insensitively) -> REVIEW.
    if window is None:
        return _review(
            "The government warning couldn't be read on this image.",
            "warning text not detected — needs a human to verify")

    has_allcaps_header = WARNING_HEADER in norm_ocr            # exact ALL CAPS
    similarity = fuzz.ratio(norm_expected, window)

    if has_allcaps_header:
        # PASS needs BOTH a high character match AND every official word present, so
        # a dropped meaning-bearing word (e.g. 'not') can't ride a high char-ratio
        # into a confident PASS — it falls to REVIEW (defer), never a wrong PASS.
        if (similarity >= WARNING_SIMILARITY_THRESHOLD
                and _all_official_words_present(window, norm_expected)):
            return FieldResult(
                field="government_warning", label="Government warning", passed=True,
                expected=expected,
                found="Official warning present (correct wording and ALL CAPS).",
                detail=f"matches 27 CFR 16.21 ({similarity:.0f}% similarity, ALL CAPS)")
        if similarity >= WARNING_REVIEW_FLOOR:
            # Header is correct and the wording is close but not a confident match —
            # most likely OCR noise on a compliant warning. Defer, don't FLAG.
            return _review(
                "Warning header is correct, but the wording couldn't be read clearly "
                "enough to confirm — please verify by eye.",
                f"close to 27 CFR 16.21 but below the confidence cutoff "
                f"({similarity:.0f}% vs {WARNING_SIMILARITY_THRESHOLD:.0f}% needed)")
        return _flag(
            "Header present, but the wording does not match the official text.",
            f"wording differs from 27 CFR 16.21 ({similarity:.0f}% similarity)")

    # No ALL-CAPS header. Is a header present in another case (a deliberate Title-case
    # violation -> crisp FLAG), or is the header region just garbled (-> defer)?
    idx = norm_ocr.lower().find(WARNING_HEADER.lower())
    header_substr = norm_ocr[idx: idx + len(WARNING_HEADER)] if idx >= 0 else ""
    header_match = fuzz.ratio(header_substr.lower(), WARNING_HEADER.lower())
    header_is_clean = header_match >= WARNING_HEADER_MATCH_THRESHOLD and not header_substr.isupper()

    if header_is_clean and similarity >= WARNING_REVIEW_FLOOR:
        # A clearly-readable header that is not ALL CAPS is a genuine 27 CFR 16.22
        # casing violation — confidently FLAG it.
        return _flag(
            "Warning present but the header is not in the required ALL CAPS.",
            "expected literal 'GOVERNMENT WARNING:' (all caps)")
    return _review(
        "The government warning header couldn't be read clearly — please verify by eye.",
        "header region didn't OCR confidently — needs a human to verify")
