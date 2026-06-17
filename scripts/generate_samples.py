"""Generate the bundled sample label images.

Produces three high-contrast labels that Tesseract reads reliably, each
demonstrating one verdict:
  clean_pass    -> brand, ABV, warning all correct
  abv_mismatch  -> label prints 7.5% while the application claims 5.0
  bad_warning   -> warning rendered in Title Case (not the required ALL CAPS)

Run:  python scripts/generate_samples.py
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

# Ensure the repo root is on sys.path so ``app`` is importable when this script
# is executed directly (python scripts/generate_samples.py).
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.reference import OFFICIAL_GOVERNMENT_WARNING  # noqa: E402
from app.samples import SAMPLES, SAMPLES_DIR  # noqa: E402

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")

# Same wording, but Title Case header + sentence case body -> must FAIL strict.
TITLECASE_WARNING = OFFICIAL_GOVERNMENT_WARNING.replace(
    "GOVERNMENT WARNING:", "Government Warning:"
)

W, H = 1000, 700

# Rendering specs that are unique to image generation: the ABV text drawn on the
# label and which warning variant to render.  Brand and filename come from the
# canonical Sample definitions in app/samples.
LABEL_SPECS: dict[str, tuple[str, str]] = {
    "clean_pass": ("ALC 5.0% BY VOL", OFFICIAL_GOVERNMENT_WARNING),
    "abv_mismatch": ("ALC 7.5% BY VOL", OFFICIAL_GOVERNMENT_WARNING),
    "bad_warning": ("ALC 5.0% BY VOL", TITLECASE_WARNING),
}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), size)


def draw_label(brand: str, abv_text: str, warning: str) -> Image.Image:
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([8, 8, W - 8, H - 8], outline="black", width=3)

    d.text((W // 2, 110), brand, font=_font(64, bold=True), fill="black", anchor="mm")
    d.text((W // 2, 210), "Craft Lager", font=_font(34), fill="black", anchor="mm")
    d.text((W // 2, 300), abv_text, font=_font(40, bold=True), fill="black", anchor="mm")
    d.text((W // 2, 360), "12 FL OZ", font=_font(28), fill="black", anchor="mm")

    wfont = _font(22)
    y = 430
    for line in textwrap.wrap(warning, width=78):
        d.text((40, y), line, font=wfont, fill="black")
        y += 30
    return img


def main() -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    for key, sample in SAMPLES.items():
        abv_text, warning = LABEL_SPECS[key]
        draw_label(sample.brand, abv_text, warning).save(sample.path)
        print(f"wrote {sample.path}")


if __name__ == "__main__":
    main()
