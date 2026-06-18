# Evaluation Report

**Goal:** < 1% margin of error, < 5 s latency.

The board scores the system on its **intended input** — the label image an agent submits with a COLA application — across clean, degraded, and varied real-product label artwork. Each case is either a **confident verdict** or a **safe deferral**; the only failure is a *confident wrong* verdict. Preprocessing ON.

| case | kind | brand | abv | warning | outcome | ms |
|------|------|-------|-----|---------|---------|----|
| clean_pass | clean | ok | ok | ok | ✅ correct | 276 |
| abv_mismatch | clean | ok | ok | ok | ✅ correct | 280 |
| bad_warning | clean | ok | ok | ok | ✅ correct | 313 |
| degraded_rotate | degraded | ok | ok | ok | ✅ correct | 310 |
| degraded_rotate_heavy | degraded | ok | ok | ok | ✅ correct | 314 |
| degraded_blur | degraded | ok | ok | ok | ✅ correct | 269 |
| degraded_jpeg | degraded | ok | ok | ok | ✅ correct | 327 |
| degraded_lowcontrast | degraded | ok | ok | ok | ✅ correct | 281 |
| degraded_perspective | degraded | ok | ok | ok | ✅ correct | 265 |
| degraded_glare | degraded | ok | ok | ok | ✅ correct | 295 |
| degraded_shadow | degraded | ok | ok | ok | ✅ correct | 302 |
| degraded_noise | degraded | ok | ok | ok | ✅ correct | 357 |
| degraded_blur_rotate | degraded | ok | ok | ok | ✅ correct | 310 |
| label_ironwood | label | ok | ok | ok | ✅ correct | 279 |
| label_harbor_light | label | ok | ok | ok | ✅ correct | 297 |
| label_redwood_trail | label | ok | ok | ok | ✅ correct | 283 |

- **Decision correctness:** 16/16 = **100.0%** — every case handled with **zero wrong verdicts** (16 confident-correct).
- **Confident coverage:** 16/16 = **100.0%** committed a verdict.
- **Margin of error (wrong ÷ confident verdicts):** 0/16 = **0.00%**  → **PASS** (< 1%)
- **Logic-on-clean accuracy:** 9/9 = **100.0%** (decision logic on clean reads)
- **Max latency:** 357 ms (budget 5000 ms) -> PASS

_Preprocessing (deskew + CLAHE contrast) lifts confident-correct verdicts on the synthetic set from 9/13 (OFF) to 13/13 (ON)._

## Out-of-scope: real-world bottle photography (stress test)

Arbitrary phone photos of bottles on a shelf — glare, reflections, dark backgrounds, thin metallic label text. This is **not** the product's input (a submitted label image); it's a stress test of what happens on input the system isn't designed to read. Not counted in the board above.

| case | kind | brand | abv | warning | outcome | ms |
|------|------|-------|-----|---------|---------|----|
| ciroc | stress | unreadable | unreadable | unreadable | ✅ safe-defer | 311 |
| grey_goose | stress | unreadable | unreadable | unreadable | ✅ safe-defer | 436 |
| jack_daniels | stress | unreadable | unreadable | unreadable | ✅ safe-defer | 533 |

_3/3 correctly **safe-defer** to human review and **zero produce a wrong verdict** — exactly the safe behaviour we want on unreadable input. Local Tesseract (a hard requirement) can't read these; the system declines to guess rather than mis-flagging a compliant label._
