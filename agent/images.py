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


class ThreadStaging:
    """Per-chat-thread staging for in-chat uploads: the image ids a thread uploaded
    plus an optional staged batch (CSV + images). Same contract as ImageStore —
    in-process, no disk, no PII — and `clear(thread_id)` evicts everything a thread
    staged (called when the user closes/clears the chat)."""

    def __init__(self) -> None:
        self._by_thread: dict[str, dict] = {}

    def _entry(self, thread_id: str) -> dict:
        return self._by_thread.setdefault(thread_id, {"image_ids": [], "batch": None})

    def add_image(self, thread_id: str, image_id: str) -> None:
        self._entry(thread_id)["image_ids"].append(image_id)

    def put_batch(self, thread_id: str, csv: bytes, images: list) -> None:
        self._entry(thread_id)["batch"] = {"csv": csv, "images": images}

    def get_batch(self, thread_id: str) -> dict | None:
        return (self._by_thread.get(thread_id) or {}).get("batch")

    def clear(self, thread_id: str) -> None:
        entry = self._by_thread.pop(thread_id, None)
        if entry:
            for image_id in entry.get("image_ids", []):
                STORE._images.pop(image_id, None)


STAGING = ThreadStaging()
