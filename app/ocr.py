"""Local OCR via Tesseract.

Deliberately local (no cloud vision API) because the target deployment
environment blocks outbound traffic to external ML endpoints. Tesseract runs
in-process and easily meets the <5s latency budget on a legible label.
"""

from __future__ import annotations

import io
import os
import re
import shutil
from pathlib import Path

import numpy as np
import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError

from . import preprocess as _preprocess

# Master switch for the OpenCV preprocessing stage (per-step toggles live in
# app/preprocess.py). On by default; flip to False to OCR the raw grayscale.
PREPROCESS_ENABLED = True


class OcrReadError(Exception):
    """Raised when an upload cannot be decoded or OCR'd.

    Lets the caller surface a friendly "couldn't read this image" result
    instead of a 500 — e.g. for a HEIC iPhone photo, a PDF, a corrupt or
    truncated file, or an image too large to process.
    """


def _configure_local_tesseract() -> None:
    """Use a no-root, locally-extracted Tesseract when the system has none.

    On a normal install (or in Docker) `tesseract` is on PATH and this is a
    no-op. In a locked-down dev box without root, we extract the .deb into
    ~/.local/tess; point pytesseract at that binary and set the runtime env
    (LD_LIBRARY_PATH / TESSDATA_PREFIX) that the subprocess will inherit.
    """
    if shutil.which("tesseract"):
        return
    prefix = Path.home() / ".local" / "tess"
    binary = prefix / "usr" / "bin" / "tesseract"
    if not binary.exists():
        return
    pytesseract.pytesseract.tesseract_cmd = str(binary)
    libdirs = [prefix / "usr" / "lib" / "x86_64-linux-gnu", prefix / "usr" / "lib"]
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = os.pathsep.join(
        [str(p) for p in libdirs] + ([existing] if existing else [])
    )
    tessdata = next(prefix.rglob("eng.traineddata"), None)
    if tessdata is not None:
        os.environ["TESSDATA_PREFIX"] = str(tessdata.parent)


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

# Mean word confidence (Tesseract reports 0-100) below this marks the read as
# marginal -> the verdict becomes "needs human review" rather than a hard
# PASS/FLAG. A single coarse threshold by design (see plan scope).
OCR_CONFIDENCE_THRESHOLD = 55.0


def _reconstruct(data: dict) -> tuple[str, float]:
    """Turn Tesseract's word-level data into (line-preserving text, mean confidence).

    Words are grouped by (block, paragraph, line) so the reconstructed text keeps
    the line breaks the brand matcher relies on; confidence is the mean over real
    words (Tesseract uses -1 for non-text boxes, which we ignore).
    """
    lines: dict[tuple, list[str]] = {}
    confs: list[float] = []
    for i, word in enumerate(data["text"]):
        if not word.strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(word)
        conf = float(data["conf"][i])
        if conf >= 0:
            confs.append(conf)
    text = "\n".join(" ".join(words) for _, words in sorted(lines.items()))
    mean_conf = sum(confs) / len(confs) if confs else 0.0
    return text, mean_conf


def extract_text_data(image_bytes: bytes) -> tuple[str, float]:
    """Return (text, mean_confidence) from one Tesseract pass.

    One `image_to_data` call yields both the text and per-word confidence, so we
    get the confidence signal without a second OCR pass (protects the <5s budget).
    Raises OcrReadError if the bytes can't be decoded or OCR'd.
    """
    _ensure_configured()
    try:
        img = _prepare(image_bytes)
        ocr_input = _maybe_preprocess(img)
        data = pytesseract.image_to_data(
            ocr_input, config=_TESS_CONFIG, output_type=pytesseract.Output.DICT
        )
    except (UnidentifiedImageError, OSError, ValueError,
            Image.DecompressionBombError, pytesseract.pytesseract.TesseractError) as exc:
        raise OcrReadError(str(exc)) from exc
    return _reconstruct(data)


def _maybe_preprocess(img: Image.Image):
    """Run OpenCV preprocessing on the grayscale image when enabled.

    Best-effort: preprocessing is an accuracy enhancement, not a hard step, so any
    OpenCV failure falls back to the raw grayscale rather than failing the OCR.
    """
    if not PREPROCESS_ENABLED:
        return img
    try:
        return _preprocess.preprocess(np.asarray(img))
    except Exception:
        return img


def extract_text(image_bytes: bytes) -> str:
    """Return just the OCR text (see extract_text_data for text + confidence)."""
    return extract_text_data(image_bytes)[0]


def is_readable(text: str) -> bool:
    """True if OCR produced enough text to trust a verdict."""
    return len(re.sub(r"\s", "", text)) >= MIN_READABLE_CHARS


# Small thumbnail for display on the results page (NOT used for re-check, so it
# can be tiny — keeps the results HTML light). Nothing is stored.
THUMBNAIL_MAX_PX = 400


def to_thumbnail_data_uri(image_bytes: bytes) -> str | None:
    """Return a small JPEG data URI for the label, or None if undecodable."""
    import base64

    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None
    longest = max(img.size)
    if longest > THUMBNAIL_MAX_PX:
        scale = THUMBNAIL_MAX_PX / longest
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"
