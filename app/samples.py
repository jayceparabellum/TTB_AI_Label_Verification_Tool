"""Bundled sample labels so a reviewer can test the deployed URL instantly.

Each sample pairs a label image with the claimed application data an agent
would have typed in, chosen to demonstrate one outcome each:
  * clean_pass     -> everything matches (PASS / PASS / PASS)
  * abv_mismatch   -> label ABV differs from the application (alcohol FLAG)
  * bad_warning    -> warning is Title Case, not ALL CAPS (warning FLAG)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SAMPLES_DIR = Path(__file__).parent / "static" / "samples"


@dataclass(frozen=True)
class Sample:
    key: str
    title: str
    filename: str
    brand: str
    alcohol_content: str
    blurb: str

    @property
    def path(self) -> Path:
        return SAMPLES_DIR / self.filename


SAMPLES = {
    s.key: s
    for s in [
        Sample(
            key="clean_pass",
            title="Clean label (should PASS)",
            filename="clean_pass.png",
            brand="Stone's Throw",
            alcohol_content="5.0",
            blurb="Brand, ABV, and warning all correct.",
        ),
        Sample(
            key="abv_mismatch",
            title="Wrong ABV (should FLAG alcohol content)",
            filename="abv_mismatch.png",
            brand="Stone's Throw",
            alcohol_content="5.0",
            blurb="Application claims 5.0% but the label prints 7.5%.",
        ),
        Sample(
            key="bad_warning",
            title="Bad warning (should FLAG government warning)",
            filename="bad_warning.png",
            brand="Stone's Throw",
            alcohol_content="5.0",
            blurb="Warning is in Title Case, not the required ALL CAPS.",
        ),
    ]
}
