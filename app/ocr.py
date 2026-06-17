"""Local OCR via Tesseract.

Deliberately local (no cloud vision API) because the target deployment
environment blocks outbound traffic to external ML endpoints. Tesseract runs
in-process and easily meets the <5s latency budget on a legible label.
"""

from __future__ import annotations

import io
import logging
import os
import re
import shutil
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)


class OcrReadError(Exception):
    """Raised when an upload cannot be decoded or OCR'd.

    Lets the caller surface a friendly "couldn't read this image" result
    instead of a 500 — e.g. for a HEIC iPhone photo, a PDF, a corrupt or
    truncated file, or an image too large to process.
    """


class TesseractNotFoundError(RuntimeError):
    """Raised when Tesseract cannot be found on PATH or in the local prefix."""


def _configure_local_tesseract() -> None:
    """Use a no-root, locally-extracted Tesseract when the system has none.

    On a normal install (or in Docker) `tesseract` is on PATH and this is a
    no-op. In a locked-down dev box without root, we extract the .deb into
    ~/.local/tess; point pytesseract at that binary and set the runtime env
    (LD_LIBRARY_PATH / TESSDATA_PREFIX) that the subprocess will inherit.

    Raises TesseractNotFoundError if no Tesseract binary can be located.
    """
    if shutil.which("tesseract"):
        return
    prefix = Path.home() / ".local" / "tess"
    binary = prefix / "usr" / "bin" / "tesseract"
    if not binary.exists():
        raise TesseractNotFoundError(
            "Tesseract OCR is not installed and no local extraction found at "
            f"{prefix}. Install with: sudo apt-get install -y tesseract-ocr"
        )
    logger.info("Using locally-extracted Tesseract at %s", binary)
    pytesseract.pytesseract.tesseract_cmd = str(binary)
    libdirs = [prefix / "usr" / "lib" / "x86_64-linux-gnu", prefix / "usr" / "lib"]
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = os.pathsep.join(
        [str(p) for p in libdirs] + ([existing] if existing else [])
    )
    tessdata = next(prefix.rglob("eng.traineddata"), None)
    if tessdata is not None:
        os.environ["TESSDATA_PREFIX"] = str(tessdata.parent)
    else:
        logger.warning(
            "Tesseract binary found at %s but eng.traineddata not located "
            "under %s — OCR may fail.",
            binary, prefix,
        )


_configured = False


def _ensure_configured() -> None:
    """Run one-time OCR setup lazily, so importing this module has no global
    side effects (env vars, pytesseract config). Called on first OCR call.
    """
    global _configured
    if _configured:
        return
    _configure_local_tesseract()
    # On constrained CPUs, Tesseract's OpenMP threads thrash; pin to one.
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    _configured = True


# If the de-whitespaced OCR output has fewer than this many characters, we treat
# the image as unreadable rather than emitting confidently-wrong FLAGs.
MIN_READABLE_CHARS = 12

# Cap the long edge so a huge phone photo doesn't blow the latency budget.
MAX_EDGE_PX = 2000

# Reject images larger than this (pixels) before decoding them — guards against
# decompression bombs. 40 MP comfortably covers any real phone/camera photo.
MAX_PIXELS = 40_000_000


def _prepare(image_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(image_bytes))
    # The header gives dimensions without decoding the pixels, so we can reject
    # an oversized/bomb image before paying to decode it.
    if img.width * img.height > MAX_PIXELS:
        raise OcrReadError(f"image too large: {img.width}x{img.height} px")
    # Respect EXIF orientation from phone cameras, then flatten to grayscale.
    img = ImageOps.exif_transpose(img)
    img = img.convert("L")
    longest = max(img.size)
    if longest > MAX_EDGE_PX:
        scale = MAX_EDGE_PX / longest
        # clamp to >=1 so an extreme aspect ratio can't produce a 0-px edge
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
    return img


# psm 6 ("assume a single uniform block of text") is ~1.7x faster than the
# default auto-segmentation on a label and keeps verdicts correct — it matters
# on CPU-constrained hosts (e.g. small cloud instances).
_TESS_CONFIG = "--psm 6"


def extract_text(image_bytes: bytes) -> str:
    """Return the raw text Tesseract reads from the label image.

    Raises OcrReadError if the bytes can't be decoded or OCR'd, so the caller
    can return a friendly "couldn't read" result rather than a 500.

    Raises TesseractNotFoundError (a RuntimeError subclass) if Tesseract is
    not installed — this is a deployment issue, not a user-input issue, and
    should surface as a 500.
    """
    _ensure_configured()
    if not image_bytes:
        raise OcrReadError("empty image payload")
    try:
        img = _prepare(image_bytes)
        return pytesseract.image_to_string(img, config=_TESS_CONFIG)
    except (UnidentifiedImageError, OSError, ValueError,
            Image.DecompressionBombError, pytesseract.pytesseract.TesseractError) as exc:
        raise OcrReadError(str(exc)) from exc


def is_readable(text: str) -> bool:
    """True if OCR produced enough text to trust a verdict."""
    return len(re.sub(r"\s", "", text)) >= MIN_READABLE_CHARS
