"""Orchestrator: OCR the label, then apply the three field matchers."""

from __future__ import annotations

import time

from . import ocr
from .matching import (
    match_alcohol_content,
    match_brand,
    match_government_warning,
)
from .models import VerificationResult
from .reference import OFFICIAL_GOVERNMENT_WARNING


def verify_label(
    image_bytes: bytes,
    brand: str,
    alcohol_content: str,
    expected_warning: str = OFFICIAL_GOVERNMENT_WARNING,
) -> VerificationResult:
    """Verify a single label image against the claimed application data."""
    start = time.perf_counter()

    text = ocr.extract_text(image_bytes)

    if not ocr.is_readable(text):
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return VerificationResult(
            readable=False,
            elapsed_ms=elapsed_ms,
            message=(
                "Couldn't read this image. Please upload a clearer, well-lit "
                "photo of the label with the text in focus."
            ),
            ocr_text=text,
        )

    fields = [
        match_brand(brand, text),
        match_alcohol_content(alcohol_content, text),
        match_government_warning(text, expected_warning),
    ]

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return VerificationResult(
        readable=True,
        fields=fields,
        elapsed_ms=elapsed_ms,
        ocr_text=text,
    )
