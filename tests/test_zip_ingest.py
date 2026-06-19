"""U2 — the shared in-memory ZIP extractor (app/ingest.py)."""

import io
import zipfile

import pytest

from app.batch import BATCH_MAX_LABELS
from app.ingest import ZipIngestError, extract_images_from_zip

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes-for-count-tests"


def _zip(entries: dict) -> bytes:
    """Build an in-memory zip from {arcname: bytes}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_happy_path_returns_images_by_basename():
    z = _zip({"a.png": PNG, "b.jpg": PNG + b"2", "c.webp": PNG + b"3"})
    out = extract_images_from_zip(z)
    assert [n for n, _ in out] == ["a.png", "b.jpg", "c.webp"]
    assert dict(out)["b.jpg"] == PNG + b"2"          # bytes round-trip exactly


def test_skips_dirs_macosx_dotfiles_and_non_images():
    z = _zip({
        "photos/": b"",                  # directory entry
        "photos/label.png": PNG,         # nested image -> kept, by basename
        "notes.txt": b"hello",           # non-image
        "__MACOSX/._label.png": b"junk", # macOS resource fork
        ".DS_Store": b"junk",            # dotfile
    })
    out = extract_images_from_zip(z)
    assert [n for n, _ in out] == ["label.png"]


def test_over_cap_rejected_not_truncated():
    z = _zip({f"l{i:02d}.png": PNG for i in range(BATCH_MAX_LABELS + 1)})
    with pytest.raises(ZipIngestError) as exc:
        extract_images_from_zip(z)
    assert str(BATCH_MAX_LABELS) in str(exc.value)   # names the limit, doesn't truncate


def test_corrupt_zip_is_friendly_error():
    with pytest.raises(ZipIngestError):
        extract_images_from_zip(b"this is not a zip at all")


def test_empty_image_set_is_friendly_error():
    z = _zip({"readme.txt": b"no images here"})
    with pytest.raises(ZipIngestError):
        extract_images_from_zip(z)


def test_per_member_size_guard():
    z = _zip({"big.png": PNG, "ok.png": PNG})
    with pytest.raises(ZipIngestError):
        extract_images_from_zip(z, max_member_bytes=len(PNG) - 1)


def test_total_size_guard():
    z = _zip({"a.png": PNG, "b.png": PNG, "c.png": PNG})
    with pytest.raises(ZipIngestError):
        extract_images_from_zip(z, max_total_bytes=len(PNG))   # one image's worth only


def test_nested_zip_entry_is_skipped_as_non_image():
    inner = _zip({"x.png": PNG})
    z = _zip({"keep.png": PNG, "inner.zip": inner})
    out = extract_images_from_zip(z)
    assert [n for n, _ in out] == ["keep.png"]               # nested archive ignored
