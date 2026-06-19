"""In-memory ZIP ingestion for batch label verification.

A user can upload a single .zip of label photos instead of hand-picking each file.
This module unzips in memory (no disk, no PII at rest), keeps only image files,
skips archive cruft (directories, __MACOSX, dotfiles, non-image entries), and guards
against zip bombs and over-cap sets. Both the /batch page and the in-chat
/agent/upload endpoint call extract_images_from_zip, so the two surfaces behave
identically — extraction is the only new logic; everything downstream (run_batch,
the verdict, the results CSV, the confirm gate) is reused unchanged.
"""

from __future__ import annotations

import io
import zipfile

from app.batch import BATCH_MAX_LABELS

# The image extensions a batch accepts (mirrors _IMAGE_EXTS in app/main.py).
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff")

# Uncompressed-size guards (mirror the per-file / per-thread upload caps in app/main.py).
MAX_MEMBER_BYTES = 10 * 1024 * 1024        # 10 MB per extracted image
MAX_TOTAL_BYTES = 50 * 1024 * 1024         # 50 MB total uncompressed per archive


class ZipIngestError(Exception):
    """A friendly, user-facing reason a zip could not be ingested."""


def _basename(name: str) -> str:
    return name.rsplit("/", 1)[-1]


def _is_image_member(info: zipfile.ZipInfo) -> bool:
    """True only for real image files — not directories, __MACOSX, or dotfiles."""
    if info.is_dir() or info.filename.startswith("__MACOSX/"):
        return False
    base = _basename(info.filename)
    if not base or base.startswith("."):
        return False
    return base.lower().endswith(IMAGE_EXTS)


def extract_images_from_zip(
    zip_bytes: bytes,
    *,
    max_files: int = BATCH_MAX_LABELS,
    max_member_bytes: int = MAX_MEMBER_BYTES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> list[tuple[str, bytes]]:
    """Return [(basename, bytes)] for every image in the zip, by original filename.

    Skips directories, __MACOSX, dotfiles, and non-image entries. Raises
    ZipIngestError on a corrupt archive, an empty image set, an over-cap image count
    (> max_files — never silently truncated), or a size-guard breach (zip-bomb
    protection). In-memory only; nothing touches disk.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ZipIngestError("That doesn't look like a valid .zip file.") from exc

    members = [i for i in zf.infolist() if _is_image_member(i)]

    if not members:
        raise ZipIngestError("No image files were found in the zip.")
    if len(members) > max_files:
        raise ZipIngestError(
            f"The zip has {len(members)} images — the batch limit is {max_files}. "
            "Please split it into smaller zips.")

    # Zip-bomb guard: reject on declared uncompressed sizes BEFORE reading any bytes.
    if any(i.file_size > max_member_bytes for i in members):
        raise ZipIngestError("A file in the zip is too large — 10 MB max per image.")
    if sum(i.file_size for i in members) > max_total_bytes:
        raise ZipIngestError(
            "The zip's contents are too large to process (over the size limit).")

    out: list[tuple[str, bytes]] = []
    total = 0
    for info in members:
        data = zf.read(info)
        total += len(data)
        if total > max_total_bytes:        # belt-and-suspenders against header lies
            raise ZipIngestError(
                "The zip's contents are too large to process (over the size limit).")
        out.append((_basename(info.filename), data))
    return out
