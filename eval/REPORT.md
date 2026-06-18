# Evaluation Report

Preprocessing OFF vs ON (OpenCV: denoise/contrast/deskew/binarize).

| case | kind | brand | abv | warning | correct | ms |
|------|------|-------|-----|---------|---------|----|
| clean_pass | clean | ok | ok | ok | PASS | 170 |
| abv_mismatch | clean | ok | ok | ok | PASS | 169 |
| bad_warning | clean | ok | ok | ok | PASS | 171 |
| degraded_rotate | degraded | ok | ok | ok | PASS | 173 |
| degraded_rotate_heavy | degraded | ok | WRONG(got False) | WRONG(got False) | MISS | 178 |
| degraded_blur | degraded | ok | ok | WRONG(got False) | MISS | 170 |
| degraded_jpeg | degraded | ok | ok | WRONG(got False) | MISS | 117 |
| degraded_lowcontrast | degraded | ok | ok | ok | PASS | 172 |

- **Logic-on-clean accuracy (ON):** 9/9 = **100.0%** (must stay 100%)
- **End-to-end accuracy:** preprocessing OFF 4/8 = **50.0%**  →  ON 5/8 = **62.5%**  (delta +12.5 pts)
- **Max latency (ON):** 178 ms (budget: 5000 ms) -> PASS

_End-to-end < 100% by design: strict warning matching is intentionally unforgiving, so the most degraded photos can still miss the warning even after preprocessing. Measured, not hidden._
