# Evaluation Report

Preprocessing OFF vs ON (OpenCV: denoise/contrast/deskew/binarize).

| case | kind | brand | abv | warning | correct | ms |
|------|------|-------|-----|---------|---------|----|
| clean_pass | clean | ok | ok | ok | PASS | 166 |
| abv_mismatch | clean | ok | ok | ok | PASS | 168 |
| bad_warning | clean | ok | ok | ok | PASS | 185 |
| degraded_rotate | degraded | ok | ok | WRONG(got False) | MISS | 178 |
| degraded_rotate_heavy | degraded | ok | ok | ok | PASS | 182 |
| degraded_blur | degraded | ok | ok | WRONG(got False) | MISS | 173 |
| degraded_jpeg | degraded | ok | ok | WRONG(got False) | MISS | 78 |
| degraded_lowcontrast | degraded | ok | ok | ok | PASS | 170 |
| degraded_perspective | degraded | ok | ok | ok | PASS | 172 |
| degraded_glare | degraded | ok | ok | ok | PASS | 168 |
| degraded_shadow | degraded | WRONG(got False) | ok | WRONG(got False) | MISS | 141 |
| degraded_noise | degraded | ok | ok | ok | PASS | 200 |
| degraded_blur_rotate | degraded | ok | ok | ok | PASS | 177 |

- **Logic-on-clean accuracy (ON):** 9/9 = **100.0%** (must stay 100%)
- **End-to-end accuracy (synthetic clean + degraded):** preprocessing OFF 7/13 = **53.8%**  →  ON 9/13 = **69.2%**  (delta +15.4 pts)
- **Max latency (ON):** 200 ms (budget: 5000 ms) -> PASS

_End-to-end < 100% by design: strict warning matching is intentionally unforgiving, so the most degraded photos can still miss the warning even after preprocessing. Measured, not hidden._

## Real-world photos

Actual phone photos (not synthetic). Graded against the TRUE verdict a human reaches from the photo, which can legitimately include a FLAG.

| case | kind | brand | abv | warning | correct | ms |
|------|------|-------|-----|---------|---------|----|
| jack_daniels | real | WRONG(got False) | ok | ok | MISS | 427 |

- **Real-world fully-correct:** 0/1 = **0.0%** (max latency 427 ms)

_Real bottle photos (glare, curved glass, small label) are the hard case: the low-confidence NEEDS REVIEW gate fires and individual fields only pass what OCR genuinely reads — so a stylized brand can MISS here while the clearly-printed ABV still matches. This is the measured real-world gap._
