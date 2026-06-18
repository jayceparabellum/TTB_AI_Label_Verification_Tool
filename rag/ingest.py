"""Load the committed CFR corpus into citable chunks.

Chunking is done at authoring time on regulatory structure (one chunk per
section/paragraph), so each chunk carries precise citation metadata — the metadata
IS the citation. Re-ingestible: swap the JSON (or point at a future live-fetched
corpus) and rebuild. Fully offline (reads a committed file, no network).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_CORPUS = Path(__file__).resolve().parent / "corpus" / "cfr_excerpts.json"
_REQUIRED = ("part", "section", "text", "source_url")


@dataclass(frozen=True)
class Chunk:
    part: str
    section: str
    paragraph: str
    beverage_type: str
    effective_date: str
    source_url: str
    heading: str
    text: str

    @property
    def citation(self) -> str:
        cite = f"27 CFR {self.section}"
        return f"{cite}{self.paragraph}" if self.paragraph else cite

    def as_metadata(self) -> dict:
        return {"citation": self.citation, "part": self.part, "section": self.section,
                "paragraph": self.paragraph, "beverage_type": self.beverage_type,
                "effective_date": self.effective_date, "source_url": self.source_url,
                "heading": self.heading}


def load_corpus(path: Path | None = None) -> list[Chunk]:
    """Parse the corpus file into validated chunks. Raises on a malformed chunk so
    a bad corpus fails loudly rather than silently dropping regulations."""
    raw = json.loads((path or _CORPUS).read_text())
    chunks = []
    for i, c in enumerate(raw.get("chunks", [])):
        missing = [k for k in _REQUIRED if not c.get(k)]
        if missing:
            raise ValueError(f"corpus chunk {i} missing required fields: {missing}")
        chunks.append(Chunk(
            part=str(c["part"]), section=str(c["section"]),
            paragraph=c.get("paragraph", ""), beverage_type=c.get("beverage_type", "all"),
            effective_date=c.get("effective_date", ""), source_url=c["source_url"],
            heading=c.get("heading", ""), text=c["text"].strip(),
        ))
    if not chunks:
        raise ValueError("corpus is empty")
    return chunks
