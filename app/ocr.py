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

import pytesseract
from PIL import Image, ImageOps


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


_configure_local_tesseract()

# If the de-whitespaced OCR output has fewer than this many characters, we treat
# the image as unreadable rather than emitting confidently-wrong FLAGs.
MIN_READABLE_CHARS = 12

# Cap the long edge so a huge phone photo doesn't blow the latency budget.
MAX_EDGE_PX = 2000


def _prepare(image_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(image_bytes))
    # Respect EXIF orientation from phone cameras, then flatten to grayscale.
    img = ImageOps.exif_transpose(img)
    img = img.convert("L")
    longest = max(img.size)
    if longest > MAX_EDGE_PX:
        scale = MAX_EDGE_PX / longest
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    return img


# psm 6 ("assume a single uniform block of text") is ~1.7x faster than the
# default auto-segmentation on a label and keeps verdicts correct — it matters
# on CPU-constrained hosts (e.g. small cloud instances).
_TESS_CONFIG = "--psm 6"

# On constrained CPUs, Tesseract's OpenMP threads thrash; pin to one.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")


def extract_text(image_bytes: bytes) -> str:
    """Return the raw text Tesseract reads from the label image."""
    img = _prepare(image_bytes)
    return pytesseract.image_to_string(img, config=_TESS_CONFIG)


def is_readable(text: str) -> bool:
    """True if OCR produced enough text to trust a verdict."""
    return len(re.sub(r"\s", "", text)) >= MIN_READABLE_CHARS
