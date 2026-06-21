"""Orchestrator: OCR the label, then apply the three field matchers."""

from __future__ import annotations

import logging
import time

from . import ocr

_log = logging.getLogger(__name__)
from . import standards
from .matching import (
    match_alcohol_content,
    match_brand,
    match_class_type,
    match_government_warning,
    match_net_contents,
)
from .matching import FieldResult
from .models import VerificationResult
from .reference import OFFICIAL_GOVERNMENT_WARNING

UNREADABLE_MESSAGE = (
    "Couldn't read this image. Please upload a clearer, well-lit "
    "photo of the label with the text in focus."
)


def _needs_review(confidence: float, fields: list[FieldResult]) -> bool:
    """Defer to a human when the read is marginal OR a field couldn't be assessed.

    Two independent signals: a low mean OCR confidence (the whole read is shaky),
    or any field marked `inconclusive` (its region didn't OCR — e.g. the warning
    block is unreadable even though the rest of the label scanned fine, which the
    global mean confidence would otherwise miss)."""
    return confidence < ocr.OCR_CONFIDENCE_THRESHOLD or any(f.inconclusive for f in fields)


def verify_fields(
    text: str,
    brand: str,
    alcohol_content: str,
    expected_warning: str = OFFICIAL_GOVERNMENT_WARNING,
    net_contents: str = "",
    class_type: str = "",
) -> list[FieldResult]:
    """Run the field matchers against already-extracted OCR text.

    Brand, alcohol content, and the government warning are always adjudicated.
    Net contents and class/type are adjudicated ONLY when a claimed value is
    supplied — an omitted field is never FLAGged, so the optional fields can't
    regress a label that didn't claim them.

    Shared by the first-pass verify (after OCR) and re-check (which reuses the
    same text), so both decide identically — re-check never re-OCRs.
    """
    fields = [
        match_brand(brand, text),
        match_alcohol_content(alcohol_content, text),
        match_government_warning(text, expected_warning),
    ]
    if net_contents and net_contents.strip():
        fields.append(match_net_contents(net_contents, text))
    if class_type and class_type.strip():
        fields.append(_adjudicate_class_type(class_type, text))
    return fields


def _adjudicate_class_type(class_type: str, text: str) -> FieldResult:
    """Class/type verdict = standards-of-identity recognition × label presence.

    Recognized designation -> keep the presence verdict (PASS when on the label),
    enriched with the controlling citation. Unrecognized -> defer to NEEDS REVIEW with
    the recommendation, **never** a confident PASS (don't pass an invalid designation)
    and **never** a confident FLAG (recognition is not an auto-rejection). (PRD 0004-style
    zero-confident-wrong posture; standards-of-identity plan KTD2.)
    """
    presence = match_class_type(class_type, text)
    rec = standards.recognize(class_type)
    if rec.recognized:
        cite = rec.citation or {}
        section = cite.get("section")
        if section:
            presence.detail = f"{presence.detail} — recognized: 27 CFR §{section}"
        return presence
    # Not a recognized class/type: defer regardless of presence, with the recommendation.
    return FieldResult(
        field="class_type", label="Class/type", passed=False,
        expected=class_type, found=presence.found,
        detail=rec.message, inconclusive=True)


def _elapsed_ms(start: float) -> int:
    """Milliseconds since `start` (time.perf_counter), as an int."""
    return int((time.perf_counter() - start) * 1000)


def _unreadable_result(start: float, ocr_text: str = "") -> VerificationResult:
    """The friendly 'couldn't read this image' result, built consistently."""
    return VerificationResult(
        readable=False,
        elapsed_ms=_elapsed_ms(start),
        message=UNREADABLE_MESSAGE,
        ocr_text=ocr_text,
    )


def reverify_text(
    text: str,
    brand: str,
    alcohol_content: str,
    expected_warning: str = OFFICIAL_GOVERNMENT_WARNING,
    confidence: float = 100.0,
    net_contents: str = "",
    class_type: str = "",
) -> VerificationResult:
    """Re-check edited claimed data against the SAME OCR text (no re-OCR).

    The label image and its text are unchanged on a re-check — only the claimed
    data changes — so running the matchers on the carried text keeps verdicts
    consistent with the original read and is instant. The OCR read quality is
    unchanged too, so the carried confidence / needs-review state is preserved.
    """
    start = time.perf_counter()
    fields = verify_fields(text, brand, alcohol_content, expected_warning,
                           net_contents=net_contents, class_type=class_type)
    return VerificationResult(
        readable=True,
        fields=fields,
        elapsed_ms=_elapsed_ms(start),
        ocr_text=text,
        confidence=confidence,
        needs_review=_needs_review(confidence, fields),
    )


def verify_label(
    image_bytes: bytes,
    brand: str,
    alcohol_content: str,
    expected_warning: str = OFFICIAL_GOVERNMENT_WARNING,
    net_contents: str = "",
    class_type: str = "",
) -> VerificationResult:
    """Verify a single label image against the claimed application data."""
    start = time.perf_counter()

    try:
        text, confidence = ocr.extract_text_data(image_bytes)
    except ocr.OcrReadError as exc:
        # Undecodable/corrupt/oversized upload (e.g. a HEIC photo or a PDF). Log it
        # (diagnosable) before returning the friendly "unreadable" result.
        _log.warning("OCR failed for upload (%d bytes): %s", len(image_bytes or b""), exc)
        return _unreadable_result(start)

    if not ocr.is_readable(text):
        return _unreadable_result(start, text)

    fields = verify_fields(text, brand, alcohol_content, expected_warning,
                           net_contents=net_contents, class_type=class_type)

    return VerificationResult(
        readable=True,
        fields=fields,
        elapsed_ms=_elapsed_ms(start),
        ocr_text=text,
        confidence=confidence,
        needs_review=_needs_review(confidence, fields),
    )
