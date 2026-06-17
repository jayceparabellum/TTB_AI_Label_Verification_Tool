# Evaluation Report

| case | kind | brand | abv | warning | correct | ms |
|------|------|-------|-----|---------|---------|----|
| clean_pass | clean | ok | ok | ok | PASS | 157 |
| abv_mismatch | clean | ok | ok | ok | PASS | 179 |
| bad_warning | clean | ok | ok | ok | PASS | 176 |
| degraded_rotate | degraded | ok | ok | WRONG(got False) | MISS | 179 |
| degraded_blur | degraded | ok | ok | WRONG(got False) | MISS | 157 |
| degraded_jpeg | degraded | ok | ok | ok | PASS | 113 |
| degraded_lowcontrast | degraded | ok | ok | ok | PASS | 158 |

- **Logic-on-clean accuracy:** 9/9 field decisions correct = **100.0%**
- **End-to-end accuracy:** 5/7 cases fully correct = **71.4%** (includes degraded/real photos)
- **Max latency:** 179 ms (budget: 5000 ms) -> PASS

_End-to-end accuracy is lower by design: strict warning matching is intentionally unforgiving, so heavily degraded photos can miss the warning. That is the documented limitation, measured rather than hidden._
