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

from PIL import Image, ImageDraw, ImageFont

# Make `app` importable when this script is run standalone (python scripts/...).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.reference import OFFICIAL_GOVERNMENT_WARNING  # noqa: E402
from app.samples import SAMPLES_DIR  # noqa: E402

OUT_DIR = SAMPLES_DIR                      # single source of truth for the samples path
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")

# The official warning lives in app.reference — import it rather than keep a copy.
OFFICIAL_WARNING = OFFICIAL_GOVERNMENT_WARNING
# Same wording, Title-Case header -> must FAIL strict. Derived, not a parallel copy.
TITLECASE_WARNING = OFFICIAL_GOVERNMENT_WARNING.replace(
    "GOVERNMENT WARNING:", "Government Warning:")

W, H = 1000, 700


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = FONT_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"DejaVu font not found at {path}. Install it with "
            "`sudo apt-get install -y fonts-dejavu-core` (Debian/Ubuntu).")
    return ImageFont.truetype(str(path), size)


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


SAMPLES = {
    "clean_pass.png": ("Stone's Throw", "ALC 5.0% BY VOL", OFFICIAL_WARNING),
    "abv_mismatch.png": ("Stone's Throw", "ALC 7.5% BY VOL", OFFICIAL_WARNING),
    "bad_warning.png": ("Stone's Throw", "ALC 5.0% BY VOL", TITLECASE_WARNING),
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, (brand, abv, warning) in SAMPLES.items():
        draw_label(brand, abv, warning).save(OUT_DIR / filename)
        print(f"wrote {OUT_DIR / filename}")


if __name__ == "__main__":
    main()
