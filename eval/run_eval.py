"""Run the evaluation set and print honest accuracy + latency numbers.

Reports TWO clearly-separated figures (per the autoplan CEO review):
  * Logic-on-clean accuracy  — decision logic on cleanly-read labels.
  * End-to-end accuracy       — full OCR + matching, including degraded photos.

Usage:  python eval/run_eval.py
Writes a markdown summary to eval/REPORT.md.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageEnhance, ImageFilter  # noqa: E402

from app.verify import verify_label  # noqa: E402
from eval.cases import CLEAN_CASES, DEGRADED_SPECS, EvalCase  # noqa: E402

logger = logging.getLogger(__name__)

IMAGES = Path(__file__).resolve().parent / "images"


def _ensure_samples() -> None:
    if not (ROOT / "app/static/samples/clean_pass.png").exists():
        import scripts.generate_samples as g

        g.main()


def _make_degraded() -> list[EvalCase]:
    """Create distorted copies of the compliant clean_pass label."""
    IMAGES.mkdir(parents=True, exist_ok=True)
    base = Image.open(ROOT / "app/static/samples/clean_pass.png").convert("RGB")
    cases = []
    for name, mode in DEGRADED_SPECS:
        img = base
        if mode == "rotate":
            img = base.rotate(5, expand=True, fillcolor="white")
        elif mode == "rotate_heavy":
            img = base.rotate(8, expand=True, fillcolor="white")
        elif mode == "blur":
            img = base.filter(ImageFilter.GaussianBlur(1.4))
        elif mode == "jpeg":
            small = base.resize((base.width // 2, base.height // 2))
            out = IMAGES / f"{name}.jpg"
            small.save(out, format="JPEG", quality=30)
            cases.append(EvalCase(name, str(out.relative_to(ROOT)),
                                  "Stone's Throw", "5.0", "degraded", True, True, True))
            continue
        elif mode == "lowcontrast":
            img = ImageEnhance.Contrast(base).enhance(0.45)
        out = IMAGES / f"{name}.png"
        img.save(out)
        cases.append(EvalCase(name, str(out.relative_to(ROOT)),
                              "Stone's Throw", "5.0", "degraded", True, True, True))
    return cases


def _real_cases() -> list[EvalCase]:
    """Any images dropped into eval/images/real/ with a sidecar .txt of
    'brand|abv' are treated as real cases expected to fully PASS."""
    out = []
    real_dir = IMAGES / "real"
    if real_dir.exists():
        for img in sorted(real_dir.glob("*")):
            if img.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                continue
            meta = img.with_suffix(".txt")
            brand, abv = "", "5.0"
            if meta.exists():
                raw = meta.read_text().strip()
                parts = raw.split("|")
                if len(parts) < 2:
                    logger.warning(
                        "Malformed metadata in %s: expected 'brand|abv', got %r. "
                        "Using defaults (brand='', abv='5.0').",
                        meta, raw,
                    )
                brand, abv = (parts + ["5.0"])[:2]
            else:
                logger.info(
                    "No metadata sidecar for %s — using defaults (brand='', abv='5.0').",
                    img.name,
                )
            out.append(EvalCase(img.stem, str(img.relative_to(ROOT)), brand, abv,
                                "real", True, True, True))
    return out


def _run(case: EvalCase):
    r = verify_label((ROOT / case.image).read_bytes(),
                     brand=case.brand, alcohol_content=case.alcohol_content)
    if not r.readable:
        return {"readable": False, "ms": r.elapsed_ms,
                "got": (None, None, None), "exp": (case.exp_brand, case.exp_alcohol, case.exp_warning)}
    got = {f.field: f.passed for f in r.fields}
    return {"readable": True, "ms": r.elapsed_ms,
            "got": (got["brand"], got["alcohol_content"], got["government_warning"]),
            "exp": (case.exp_brand, case.exp_alcohol, case.exp_warning)}


def _score(cases: list[EvalCase]) -> dict:
    """Run every case at the current preprocessing setting; collect the tallies."""
    clean_c = clean_t = e2e_c = e2e_t = 0
    max_ms = 0
    rows = []
    for c in cases:
        res = _run(c)
        max_ms = max(max_ms, res["ms"])
        if not res["readable"]:
            cells, case_ok = ["unreadable"] * 3, False
        else:
            cells, case_ok = [], True
            for i in range(3):
                ok = res["got"][i] == res["exp"][i]
                case_ok = case_ok and ok
                cells.append("ok" if ok else f"WRONG(got {res['got'][i]})")
                if c.kind == "clean":
                    clean_t += 1
                    clean_c += int(ok)
        e2e_t += 1
        e2e_c += int(case_ok)
        rows.append((c, cells, case_ok, res["ms"]))
    return {"clean_c": clean_c, "clean_t": clean_t, "e2e_c": e2e_c,
            "e2e_t": e2e_t, "max_ms": max_ms, "rows": rows}


def main() -> None:
    _ensure_samples()
    cases = CLEAN_CASES + _make_degraded() + _real_cases()

    from app import ocr  # toggle preprocessing for the before/after (U4)

    ocr.PREPROCESS_ENABLED = False
    off = _score(cases)
    ocr.PREPROCESS_ENABLED = True
    on = _score(cases)

    def pct(c, t):
        return 100.0 * c / max(t, 1)

    lines = ["# Evaluation Report", "",
             "Preprocessing OFF vs ON (OpenCV: denoise/contrast/deskew/binarize).", "",
             "| case | kind | brand | abv | warning | correct | ms |",
             "|------|------|-------|-----|---------|---------|----|"]
    for c, cells, case_ok, ms in on["rows"]:        # detailed table = ON run
        lines.append(f"| {c.name} | {c.kind} | {cells[0]} | {cells[1]} | {cells[2]} "
                     f"| {'PASS' if case_ok else 'MISS'} | {ms} |")

    e2e_off, e2e_on = pct(off["e2e_c"], off["e2e_t"]), pct(on["e2e_c"], on["e2e_t"])
    lines += [
        "",
        f"- **Logic-on-clean accuracy (ON):** {on['clean_c']}/{on['clean_t']} "
        f"= **{pct(on['clean_c'], on['clean_t']):.1f}%** (must stay 100%)",
        f"- **End-to-end accuracy:** preprocessing OFF "
        f"{off['e2e_c']}/{off['e2e_t']} = **{e2e_off:.1f}%**  →  ON "
        f"{on['e2e_c']}/{on['e2e_t']} = **{e2e_on:.1f}%**  "
        f"(delta {e2e_on - e2e_off:+.1f} pts)",
        f"- **Max latency (ON):** {on['max_ms']} ms (budget: 5000 ms) "
        f"-> {'PASS' if on['max_ms'] < 5000 else 'FAIL'}",
        "",
        "_End-to-end < 100% by design: strict warning matching is intentionally "
        "unforgiving, so the most degraded photos can still miss the warning even "
        "after preprocessing. Measured, not hidden._",
    ]

    report = "\n".join(lines)
    (Path(__file__).resolve().parent / "REPORT.md").write_text(report + "\n")
    print(report)


if __name__ == "__main__":
    main()
