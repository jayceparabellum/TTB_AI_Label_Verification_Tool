# Evaluation Report

Preprocessing OFF vs ON (OpenCV: denoise/contrast/deskew/binarize).

| case | kind | brand | abv | warning | correct | ms |
|------|------|-------|-----|---------|---------|----|
| clean_pass | clean | ok | ok | ok | PASS | 166 |
| abv_mismatch | clean | ok | ok | ok | PASS | 172 |
| bad_warning | clean | ok | ok | ok | PASS | 167 |
| degraded_rotate | degraded | ok | ok | WRONG(got False) | MISS | 177 |
| degraded_rotate_heavy | degraded | ok | ok | ok | PASS | 181 |
| degraded_blur | degraded | ok | ok | WRONG(got False) | MISS | 170 |
| degraded_jpeg | degraded | ok | ok | WRONG(got False) | MISS | 75 |
| degraded_lowcontrast | degraded | ok | ok | ok | PASS | 169 |
| degraded_perspective | degraded | ok | ok | ok | PASS | 170 |
| degraded_glare | degraded | ok | ok | ok | PASS | 169 |
| degraded_shadow | degraded | ok | ok | WRONG(got False) | MISS | 143 |
| degraded_noise | degraded | ok | ok | ok | PASS | 201 |
| degraded_blur_rotate | degraded | ok | ok | ok | PASS | 185 |

- **Logic-on-clean accuracy (ON):** 9/9 = **100.0%** (must stay 100%)
- **End-to-end accuracy:** preprocessing OFF 7/13 = **53.8%**  →  ON 9/13 = **69.2%**  (delta +15.4 pts)
- **Max latency (ON):** 201 ms (budget: 5000 ms) -> PASS

_End-to-end < 100% by design: strict warning matching is intentionally unforgiving, so the most degraded photos can still miss the warning even after preprocessing. Measured, not hidden._
