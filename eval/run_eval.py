"""Run the evaluation set and print honest accuracy + latency numbers.

Reports TWO clearly-separated figures (per the autoplan CEO review):
  * Logic-on-clean accuracy  — decision logic on cleanly-read labels.
  * End-to-end accuracy       — full OCR + matching, including degraded photos.

Usage:  python eval/run_eval.py
Writes a markdown summary to eval/REPORT.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageEnhance, ImageFilter  # noqa: E402

from app.verify import verify_label  # noqa: E402
from eval.cases import CLEAN_CASES, DEGRADED_SPECS, EvalCase  # noqa: E402

IMAGES = Path(__file__).resolve().parent / "images"


def _ensure_samples() -> None:
    if not (ROOT / "app/static/samples/clean_pass.png").exists():
        import scripts.generate_samples as g

        g.main()


def _perspective(base: Image.Image) -> Image.Image:
    """Keystone warp: simulate photographing the label from a low angle."""
    a = cv2.cvtColor(np.asarray(base), cv2.COLOR_RGB2BGR)
    h, w = a.shape[:2]
    dx = w * 0.12
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[dx, 0], [w - dx, 0], [w, h], [0, h]])  # top edge pulled in
    m = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(a, m, (w, h), borderValue=(255, 255, 255))
    return Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))


def _glare(base: Image.Image) -> Image.Image:
    """Bright overexposed wash across the upper-left (camera flash / sunlight)."""
    a = np.asarray(base).astype(np.float32)
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    # bright blob centered up-left, falling off with distance
    d = np.sqrt((xx - w * 0.35) ** 2 + (yy - h * 0.3) ** 2)
    glow = np.clip(1.0 - d / (0.6 * max(h, w)), 0, 1)[..., None] * 130
    return Image.fromarray(np.clip(a + glow, 0, 255).astype(np.uint8))


def _shadow(base: Image.Image) -> Image.Image:
    """Uneven lighting: a left-to-right darkening gradient (one side in shadow)."""
    a = np.asarray(base).astype(np.float32)
    w = a.shape[1]
    ramp = np.linspace(0.45, 1.0, w)[None, :, None]  # 0.45x on the left edge
    return Image.fromarray(np.clip(a * ramp, 0, 255).astype(np.uint8))


def _noise(base: Image.Image) -> Image.Image:
    """Additive Gaussian sensor grain (deterministic seed for a stable eval)."""
    a = np.asarray(base).astype(np.float32)
    rng = np.random.default_rng(1234)
    noisy = a + rng.normal(0, 18, a.shape)
    return Image.fromarray(np.clip(noisy, 0, 255).astype(np.uint8))


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
        elif mode == "perspective":
            img = _perspective(base)
        elif mode == "glare":
            img = _glare(base)
        elif mode == "shadow":
            img = _shadow(base)
        elif mode == "noise":
            img = _noise(base)
        elif mode == "blur_rotate":
            img = base.filter(ImageFilter.GaussianBlur(1.0)).rotate(
                6, expand=True, fillcolor="white")
        out = IMAGES / f"{name}.png"
        img.save(out)
        cases.append(EvalCase(name, str(out.relative_to(ROOT)),
                              "Stone's Throw", "5.0", "degraded", True, True, True))
    return cases


def _verdict(token: str, default: bool) -> bool:
    t = token.strip().lower()
    if t in {"pass", "p", "1", "true", "yes", "ok"}:
        return True
    if t in {"flag", "fail", "f", "0", "false", "no"}:
        return False
    return default


def _real_cases() -> list[EvalCase]:
    """Real photos in eval/images/real/, each with a sidecar .txt:

        brand|abv[|exp_brand,exp_alcohol,exp_warning]

    The optional third field is the TRUE per-field verdict a perfect human reader
    reaches FROM THE PHOTO (pass/flag), defaulting to all-pass. '#' lines are
    comments. Unlike the synthetic degraded set (all derived from a compliant
    label), real photos can carry a genuine FLAG — e.g. an export bottle with no
    US §16.21 warning — so the eval grades against the real truth, not an
    assumed PASS."""
    out = []
    real_dir = IMAGES / "real"
    if not real_dir.exists():
        return out
    for img in sorted(real_dir.glob("*")):
        if img.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            continue
        meta = img.with_suffix(".txt")
        brand, abv = "", "5.0"
        eb = ea = ew = True
        if meta.exists():
            lines = [ln for ln in meta.read_text().splitlines()
                     if ln.strip() and not ln.lstrip().startswith("#")]
            if lines:
                parts = [p.strip() for p in lines[0].split("|")]
                brand = parts[0] if parts else ""
                if len(parts) > 1 and parts[1]:
                    abv = parts[1]
                if len(parts) > 2 and parts[2]:
                    v = [x.strip() for x in parts[2].split(",")]
                    eb = _verdict(v[0], True) if len(v) > 0 else True
                    ea = _verdict(v[1], True) if len(v) > 1 else True
                    ew = _verdict(v[2], True) if len(v) > 2 else True
        out.append(EvalCase(img.stem, str(img.relative_to(ROOT)), brand, abv,
                            "real", eb, ea, ew))
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
    # Synthetic set (clean + degraded) drives the comparable preprocessing
    # benchmark; real photos are graded separately so one hard anecdote doesn't
    # move the controlled number.
    synthetic = CLEAN_CASES + _make_degraded()
    real = _real_cases()

    from app import ocr  # toggle preprocessing for the before/after (U4)

    ocr.PREPROCESS_ENABLED = False
    off = _score(synthetic)
    ocr.PREPROCESS_ENABLED = True
    on = _score(synthetic)
    real_on = _score(real) if real else None

    def pct(c, t):
        return 100.0 * c / max(t, 1)

    def table(rows):
        out = ["| case | kind | brand | abv | warning | correct | ms |",
               "|------|------|-------|-----|---------|---------|----|"]
        for c, cells, case_ok, ms in rows:
            out.append(f"| {c.name} | {c.kind} | {cells[0]} | {cells[1]} | {cells[2]} "
                       f"| {'PASS' if case_ok else 'MISS'} | {ms} |")
        return out

    lines = ["# Evaluation Report", "",
             "Preprocessing OFF vs ON (OpenCV: denoise/contrast/deskew/binarize).", ""]
    lines += table(on["rows"])        # detailed table = synthetic ON run

    e2e_off, e2e_on = pct(off["e2e_c"], off["e2e_t"]), pct(on["e2e_c"], on["e2e_t"])
    lines += [
        "",
        f"- **Logic-on-clean accuracy (ON):** {on['clean_c']}/{on['clean_t']} "
        f"= **{pct(on['clean_c'], on['clean_t']):.1f}%** (must stay 100%)",
        f"- **End-to-end accuracy (synthetic clean + degraded):** preprocessing OFF "
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

    if real_on:
        lines += [
            "",
            "## Real-world photos",
            "",
            "Actual phone photos (not synthetic). Graded against the TRUE verdict a "
            "human reaches from the photo, which can legitimately include a FLAG.",
            "",
        ]
        lines += table(real_on["rows"])
        lines += [
            "",
            f"- **Real-world fully-correct:** {real_on['e2e_c']}/{real_on['e2e_t']} "
            f"= **{pct(real_on['e2e_c'], real_on['e2e_t']):.1f}%** "
            f"(max latency {real_on['max_ms']} ms)",
            "",
            "_Real bottle photos (glare, curved glass, small label) are the hard case: "
            "the low-confidence NEEDS REVIEW gate fires and individual fields only pass "
            "what OCR genuinely reads — so a stylized brand can MISS here while the "
            "clearly-printed ABV still matches. This is the measured real-world gap._",
        ]

    report = "\n".join(lines)
    (Path(__file__).resolve().parent / "REPORT.md").write_text(report + "\n")
    print(report)


if __name__ == "__main__":
    main()
