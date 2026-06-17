# Evaluation Report

| case | kind | brand | abv | warning | correct | ms |
|------|------|-------|-----|---------|---------|----|
| clean_pass | clean | ok | ok | ok | PASS | 184 |
| abv_mismatch | clean | ok | ok | ok | PASS | 183 |
| bad_warning | clean | ok | ok | ok | PASS | 183 |
| degraded_rotate | degraded | ok | ok | WRONG(got False) | MISS | 209 |
| degraded_blur | degraded | ok | ok | WRONG(got False) | MISS | 179 |
| degraded_jpeg | degraded | ok | ok | WRONG(got False) | MISS | 82 |
| degraded_lowcontrast | degraded | ok | ok | ok | PASS | 195 |

- **Logic-on-clean accuracy:** 9/9 field decisions correct = **100.0%**
- **End-to-end accuracy:** 4/7 cases fully correct = **57.1%** (includes degraded/real photos)
- **Max latency:** 209 ms (budget: 5000 ms) -> PASS

_End-to-end accuracy is lower by design: strict warning matching is intentionally unforgiving, so heavily degraded photos can miss the warning. That is the documented limitation, measured rather than hidden._
