"""Orchestrator: OCR the label, then apply the three field matchers."""

from __future__ import annotations

import time

from . import ocr
from .matching import (
    match_alcohol_content,
    match_brand,
    match_government_warning,
)
from .matching import FieldResult
from .models import VerificationResult
from .reference import OFFICIAL_GOVERNMENT_WARNING

UNREADABLE_MESSAGE = (
    "Couldn't read this image. Please upload a clearer, well-lit "
    "photo of the label with the text in focus."
)


def verify_fields(
    text: str,
    brand: str,
    alcohol_content: str,
    expected_warning: str = OFFICIAL_GOVERNMENT_WARNING,
) -> list[FieldResult]:
    """Run the three field matchers against already-extracted OCR text.

    Shared by the first-pass verify (after OCR) and re-check (which reuses the
    same text), so both decide identically — re-check never re-OCRs.
    """
    return [
        match_brand(brand, text),
        match_alcohol_content(alcohol_content, text),
        match_government_warning(text, expected_warning),
    ]


def reverify_text(
    text: str,
    brand: str,
    alcohol_content: str,
    expected_warning: str = OFFICIAL_GOVERNMENT_WARNING,
    confidence: float = 100.0,
) -> VerificationResult:
    """Re-check edited claimed data against the SAME OCR text (no re-OCR).

    The label image and its text are unchanged on a re-check — only the claimed
    brand/ABV change — so running the matchers on the carried text keeps verdicts
    consistent with the original read and is instant. The OCR read quality is
    unchanged too, so the carried confidence / needs-review state is preserved.
    """
    start = time.perf_counter()
    fields = verify_fields(text, brand, alcohol_content, expected_warning)
    return VerificationResult(
        readable=True,
        fields=fields,
        elapsed_ms=int((time.perf_counter() - start) * 1000),
        ocr_text=text,
        confidence=confidence,
        needs_review=confidence < ocr.OCR_CONFIDENCE_THRESHOLD,
    )


def verify_label(
    image_bytes: bytes,
    brand: str,
    alcohol_content: str,
    expected_warning: str = OFFICIAL_GOVERNMENT_WARNING,
) -> VerificationResult:
    """Verify a single label image against the claimed application data."""
    start = time.perf_counter()

    try:
        text, confidence = ocr.extract_text_data(image_bytes)
    except ocr.OcrReadError:
        # Undecodable/corrupt/oversized upload (e.g. a HEIC photo or a PDF).
        return VerificationResult(
            readable=False,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            message=UNREADABLE_MESSAGE,
            ocr_text="",
        )

    if not ocr.is_readable(text):
        return VerificationResult(
            readable=False,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            message=UNREADABLE_MESSAGE,
            ocr_text=text,
        )

    fields = verify_fields(text, brand, alcohol_content, expected_warning)

    return VerificationResult(
        readable=True,
        fields=fields,
        elapsed_ms=int((time.perf_counter() - start) * 1000),
        ocr_text=text,
        confidence=confidence,
        needs_review=confidence < ocr.OCR_CONFIDENCE_THRESHOLD,
    )
