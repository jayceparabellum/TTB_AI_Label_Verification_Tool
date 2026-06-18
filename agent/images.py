"""Tiny in-process store mapping an image id -> raw bytes.

The web layer puts an uploaded image here and sets `active_image_id` in the agent
state; tools read the bytes by id (never from model-supplied args). Stateless POC:
nothing is persisted to disk, so no PII lingers. Bundled samples are seeded by
their sample key so tests and prompt chips have something to verify.
"""

from __future__ import annotations

import uuid
from pathlib import Path

_SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"


class ImageStore:
    def __init__(self) -> None:
        self._images: dict[str, bytes] = {}

    def put(self, data: bytes, image_id: str | None = None) -> str:
        image_id = image_id or uuid.uuid4().hex
        self._images[image_id] = data
        return image_id

    def get(self, image_id: str) -> bytes | None:
        return self._images.get(image_id)

    def seed_samples(self) -> dict[str, str]:
        """Load bundled sample PNGs under their key (e.g. 'clean_pass'). Returns
        {sample_key: image_id} — here the id IS the key for easy reference."""
        out = {}
        if _SAMPLES.exists():
            for png in _SAMPLES.glob("*.png"):
                out[png.stem] = self.put(png.read_bytes(), image_id=png.stem)
        return out


# Process-wide singleton (POC). Reset in tests via STORE._images.clear().
STORE = ImageStore()
