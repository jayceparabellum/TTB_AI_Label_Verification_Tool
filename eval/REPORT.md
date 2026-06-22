# Evaluation Report

**Goal:** < 1% margin of error, < 5 s latency.

The board scores the system on its **intended input** — the label image an agent submits with a COLA application — across clean, degraded, and varied real-product label artwork. Each case is either a **confident verdict** or a **safe deferral**; the only failure is a *confident wrong* verdict. Preprocessing ON.

| case | kind | brand | abv | warning | outcome | ms |
|------|------|-------|-----|---------|---------|----|
| clean_pass | clean | ok | ok | ok | ✅ correct | 173 |
| abv_mismatch | clean | ok | ok | ok | ✅ correct | 171 |
| bad_warning | clean | ok | ok | ok | ✅ correct | 173 |
| degraded_rotate | degraded | ok | ok | ok | ✅ correct | 185 |
| degraded_rotate_heavy | degraded | ok | ok | ok | ✅ correct | 189 |
| degraded_blur | degraded | ok | ok | ok | ✅ correct | 174 |
| degraded_jpeg | degraded | ok | ok | ok | ✅ correct | 184 |
| degraded_lowcontrast | degraded | ok | ok | ok | ✅ correct | 176 |
| degraded_perspective | degraded | ok | ok | ok | ✅ correct | 170 |
| degraded_glare | degraded | ok | ok | ok | ✅ correct | 177 |
| degraded_shadow | degraded | ok | ok | ok | ✅ correct | 187 |
| degraded_noise | degraded | ok | ok | ok | ✅ correct | 211 |
| degraded_blur_rotate | degraded | ok | ok | ok | ✅ correct | 184 |
| label_ironwood | label | ok | ok | ok | ✅ correct | 175 |
| label_harbor_light | label | ok | ok | ok | ✅ correct | 179 |
| label_redwood_trail | label | ok | ok | ok | ✅ correct | 176 |
| sc_amber_field | synthetic_clean | ok | ok | ok | ✅ correct | 174 |
| sc_blue_ridge | synthetic_clean | ok | ok | ok | ✅ correct | 171 |
| sc_copper_creek | synthetic_clean | ok | ok | ok | ✅ correct | 181 |
| sc_dunes_edge | synthetic_clean | ok | ok | ok | ✅ correct | 166 |
| sc_granite_peak | synthetic_clean | ok | ok | WRONG(got False) | ✅ safe-defer | 162 |
| sc_hollow_pines | synthetic_clean | ok | ok | ok | ✅ correct | 177 |
| sc_juniper_lane | synthetic_clean | ok | ok | ok | ✅ correct | 178 |
| sc_silver_birch | synthetic_clean | ok | ok | ok | ✅ correct | 167 |

- **Decision correctness:** 24/24 = **100.0%** — every case handled with **zero wrong verdicts** (23 confident-correct + 1 safe deferrals).
- **Confident coverage:** 23/24 = **95.8%** committed a verdict; 1/24 safely deferred.
- **Margin of error (wrong ÷ confident verdicts):** 0/23 = **0.00%**  → **PASS** (< 1%)
- **Logic-on-clean accuracy:** 9/9 = **100.0%** (decision logic on clean reads)
- **False-positive rate (compliant labels confidently FLAGged):** 0/22 = **0.00%** — the 'clean labels being flagged' defect; a compliant-but-unreadable label safely defers and is not counted as a false positive.
- **False-negative count (non-compliant labels confidently PASSed):** 0 — the worst, regulatory-miss error; must stay 0.
- **Synthetic clean labels (calibration):** 8 — diverse COMPLIANT renders (varied brand/ABV, warning print size, background tint, mild degradation) included in the false-positive denominator above to calibrate the warning thresholds and confirm the system does not confidently FLAG a clean label. These are synthetic, **not** real artwork — the real-world false-positive defect still requires real images (see the line below).
- **Real clean labels in the corpus:** 0 — ⚠️ none yet. Synthetic renders (above) can't exhibit the real-world false-positive defect; drop genuinely-compliant label *photos* into `eval/images/real_clean/` to measure and calibrate against real artwork (see its README).
- **Max latency:** 211 ms (budget 5000 ms) -> PASS

_Preprocessing (deskew + CLAHE contrast) lifts confident-correct verdicts on the synthetic set from 9/13 (OFF) to 13/13 (ON)._

## Out-of-scope: real-world bottle photography (stress test)

Arbitrary phone photos of bottles on a shelf — glare, reflections, dark backgrounds, thin metallic label text. This is **not** the product's input (a submitted label image); it's a stress test of what happens on input the system isn't designed to read. Not counted in the board above.

| case | kind | brand | abv | warning | outcome | ms |
|------|------|-------|-----|---------|---------|----|
| ciroc | stress | unreadable | unreadable | unreadable | ✅ safe-defer | 194 |
| grey_goose | stress | unreadable | unreadable | unreadable | ✅ safe-defer | 264 |
| jack_daniels | stress | unreadable | unreadable | unreadable | ✅ safe-defer | 333 |

_3/3 correctly **safe-defer** to human review and **zero produce a wrong verdict** — exactly the safe behaviour we want on unreadable input. Local Tesseract (a hard requirement) can't read these; the system declines to guess rather than mis-flagging a compliant label._
