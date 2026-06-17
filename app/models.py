"""Result data structures shared between the verifier and the web layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .matching import FieldResult


@dataclass
class VerificationResult:
    """The full outcome of verifying one label against its application data."""

    readable: bool
    fields: List[FieldResult] = field(default_factory=list)
    elapsed_ms: int = 0
    message: str = ""          # used when the image is unreadable
    ocr_text: str = ""         # raw OCR output, for transparency/debugging

    @property
    def overall_pass(self) -> bool:
        return self.readable and bool(self.fields) and all(f.passed for f in self.fields)

    @property
    def flagged_count(self) -> int:
        return sum(1 for f in self.fields if not f.passed)
