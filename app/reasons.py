"""Detailed, human-readable reasons for why a field was flagged or deferred.

Deterministic and offline — a fixed mapping from a FieldResult's (field, outcome)
to a plain-language reason, a concrete "what to check", and the controlling 27 CFR
reference. No OCR, no LLM, no RAG: this never affects the verdict or the <5 s path;
it only explains the verdict the deterministic core already produced, so a reviewer
sees exactly why each flag exists (Six Sigma verification, 2026-06-19).

PASS fields return None (no explanation needed). Non-passing fields return a dict:
  {status, reason, what_to_check, citation}
where status is "FLAG" (confident: genuinely wrong) or "REVIEW" (inconclusive:
couldn't be read confidently — defer to a human, never a confident verdict).
"""

from __future__ import annotations

from .models import FieldResult

# Controlling references per field. Brand/ABV requirements are commodity-specific
# (wine Part 4, distilled spirits Part 5, malt beverages Part 7), so those cite the
# parallel sections; the health-warning sections are fixed.
_CITATIONS = {
    "brand": "27 CFR §4.33 / §5.63 / §7.63 — brand name must appear and match the approved application.",
    "alcohol_content": "27 CFR §4.36 / §5.65 / §7.65 — alcohol-content statement and its tolerances.",
    "government_warning": "27 CFR §16.21 (required statement) and §16.22 (form: literal ALL-CAPS 'GOVERNMENT WARNING:').",
}

_FLAG_REASONS = {
    "brand": (
        "The brand name read from the label isn't a close enough match to the "
        "application. Case, punctuation, and spacing differences are tolerated, so "
        "this means the names genuinely differ (or the brand text didn't scan cleanly).",
        "Compare the brand on the label artwork against the application's brand name.",
    ),
    "alcohol_content": (
        "The alcohol content on the label doesn't match the application's claimed "
        "value. Values are compared as numbers (5 = 5.0%, and proof = 2× ABV is "
        "understood), so this is a genuine numeric difference.",
        "Read the ABV or proof printed on the label and confirm it equals the application.",
    ),
    "government_warning": (
        "The Government Warning is readable but does not match the mandated statement "
        "— either the header is not in the required ALL CAPS or the wording differs "
        "from the official §16.21 text.",
        "Compare the label's warning against the verbatim §16.21 statement; the header "
        "must be the literal 'GOVERNMENT WARNING:' in all capital letters.",
    ),
}

_REVIEW_REASONS = {
    "government_warning": (
        "The Government Warning appears to be present, but it couldn't be read "
        "confidently enough to confirm the exact wording and casing — so it's "
        "deferred to a human rather than passed or failed.",
        "Visually confirm the label carries the exact §16.21 statement with the "
        "ALL-CAPS 'GOVERNMENT WARNING:' header.",
    ),
}

# Finer-grained review reasons keyed by (field, review_kind). When a matcher tags an
# inconclusive result with a review_kind, prefer the matching message here over the
# generic per-field one above — it tells the reviewer *why* it deferred.
_REVIEW_REASONS_BY_KIND = {
    ("government_warning", "absent"): (
        "No Government Warning was found on this label, even though the rest of it "
        "read clearly — it appears to be missing. Because the system never confidently "
        "fails an item it might have misread, this is deferred for you to confirm by eye "
        "rather than auto-failed.",
        "Confirm by eye whether the label actually carries the §16.21 'GOVERNMENT "
        "WARNING:' statement at all. If it is genuinely absent, the label is non-compliant.",
    ),
    ("government_warning", "unreadable"): (
        "The Government Warning region didn't read clearly enough to confirm its wording "
        "and casing, so it's deferred to a human rather than passed or failed.",
        "Visually confirm the label carries the exact §16.21 statement with the "
        "ALL-CAPS 'GOVERNMENT WARNING:' header.",
    ),
}

_GENERIC_REVIEW = (
    "This field couldn't be read confidently from the image, so it's deferred to a "
    "human instead of being passed or failed.",
    "Check this field on the label artwork by eye.",
)


def explain(field: FieldResult) -> dict | None:
    """Return a detailed reason for a non-passing field, or None if it passed."""
    if field.passed:
        return None

    if field.inconclusive:
        reason, what = _REVIEW_REASONS_BY_KIND.get(
            (field.field, field.review_kind),
            _REVIEW_REASONS.get(field.field, _GENERIC_REVIEW))
        status = "REVIEW"
    else:
        reason, what = _FLAG_REASONS.get(
            field.field,
            ("This field did not match the application.",
             "Compare this field on the label against the application."))
        status = "FLAG"

    # Fold the matcher's terse detail in so the reviewer sees the measured signal too.
    if field.detail:
        what = f"{what} ({field.detail})"

    return {
        "status": status,
        "reason": reason,
        "what_to_check": what,
        "citation": _CITATIONS.get(field.field, ""),
    }
