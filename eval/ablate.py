"""Ablate the OpenCV preprocessing steps over the full eval set.

Runs every on/off combination of the four preprocessing steps
(denoise/contrast/deskew/binarize) against clean + degraded cases and ranks
them by end-to-end accuracy, then latency. Use this to re-tune `STEPS` in
app/preprocess.py when the deployment's photo profile changes (e.g. lots of
rotation vs. lots of low light).

Usage:  python eval/ablate.py
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import ocr, preprocess          # noqa: E402
from eval import run_eval                 # noqa: E402
from eval.cases import CLEAN_CASES        # noqa: E402

STEP_KEYS = ["denoise", "contrast", "deskew", "binarize"]


def _score(cases) -> tuple[float, float, int, int, int]:
    s = run_eval._score(cases)
    clean = 100.0 * s["clean_c"] / max(s["clean_t"], 1)
    e2e = 100.0 * s["e2e_c"] / max(s["e2e_t"], 1)
    return clean, e2e, s["e2e_c"], s["e2e_t"], s["max_ms"]


def main() -> None:
    run_eval._ensure_samples()
    cases = CLEAN_CASES + run_eval._make_degraded()
    n_deg = sum(1 for c in cases if c.kind == "degraded")
    print(f"{len(cases)} cases ({n_deg} degraded)\n")

    ocr.PREPROCESS_ENABLED = False
    b_clean, b_e2e, b_c, b_t, b_ms = _score(cases)
    print(f"OFF                  clean={b_clean:5.1f}  e2e={b_e2e:5.1f} ({b_c}/{b_t})  ms={b_ms}")

    ocr.PREPROCESS_ENABLED = True
    rows = []
    for combo in itertools.product([False, True], repeat=4):
        preprocess.STEPS = dict(zip(STEP_KEYS, combo))
        clean, e2e, c, t, ms = _score(cases)
        label = "+".join(k for k, v in zip(STEP_KEYS, combo) if v) or "(none)"
        rows.append((e2e, -ms, clean, c, t, ms, label))

    rows.sort(reverse=True)
    print("\nrank   e2e   clean  cases   ms   steps")
    for i, (e2e, _, clean, c, t, ms, label) in enumerate(rows, 1):
        flag = "" if clean >= 100.0 else "  <-- REGRESSES CLEAN"
        print(f"{i:>2}.   {e2e:5.1f}  {clean:5.1f}  {c}/{t}  {ms:>4}  {label}{flag}")


if __name__ == "__main__":
    main()
