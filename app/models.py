"""Result data structures shared between the verifier and the web layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .matching import FieldResult


@dataclass
class VerificationResult:
    """The full outcome of verifying one label against its application data."""

    readable: bool
    fields: List[FieldResult] = field(default_factory=list)
    elapsed_ms: int = 0
    message: str = ""          # used when the image is unreadable
    ocr_text: str = ""         # raw OCR output, for transparency/debugging
    confidence: float = 100.0  # mean OCR word confidence (0-100)
    needs_review: bool = False  # OCR read was marginal -> ask a human

    @property
    def overall_pass(self) -> bool:
        return (
            self.readable
            and not self.needs_review
            and bool(self.fields)
            and all(f.passed for f in self.fields)
        )

    @property
    def flagged_count(self) -> int:
        return sum(1 for f in self.fields if not f.passed)

    @property
    def verdicts(self) -> Dict[str, bool]:
        """Map field name -> passed, e.g. ``{"brand": True, ...}``."""
        return {f.field: f.passed for f in self.fields}
