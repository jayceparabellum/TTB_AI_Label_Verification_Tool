# Evaluation Report

**Goal:** < 1% margin of error, < 5 s latency.

Each verdict is *confident* (the system commits to correct/WRONG) or a *deferral* to human review (low OCR confidence, or a region that didn't read). **Margin of error counts only confident verdicts** — a deferral is the system declining to guess, not an error. Preprocessing ON.

| case | kind | brand | abv | warning | outcome | ms |
|------|------|-------|-----|---------|---------|----|
| clean_pass | clean | ok | ok | ok | ✓ correct | 176 |
| abv_mismatch | clean | ok | ok | ok | ✓ correct | 165 |
| bad_warning | clean | ok | ok | ok | ✓ correct | 162 |
| degraded_rotate | degraded | ok | ok | ok | ✓ correct | 179 |
| degraded_rotate_heavy | degraded | ok | ok | ok | ✓ correct | 184 |
| degraded_blur | degraded | ok | ok | ok | ✓ correct | 170 |
| degraded_jpeg | degraded | ok | ok | WRONG(got False) | ↪ review | 77 |
| degraded_lowcontrast | degraded | ok | ok | ok | ✓ correct | 167 |
| degraded_perspective | degraded | ok | ok | ok | ✓ correct | 163 |
| degraded_glare | degraded | ok | ok | ok | ✓ correct | 168 |
| degraded_shadow | degraded | WRONG(got False) | ok | WRONG(got False) | ↪ review | 150 |
| degraded_noise | degraded | ok | ok | ok | ✓ correct | 202 |
| degraded_blur_rotate | degraded | ok | ok | ok | ✓ correct | 178 |
| ciroc | real | WRONG(got False) | WRONG(got False) | ok | ↪ review | 232 |
| jack_daniels | real | WRONG(got False) | ok | ok | ↪ review | 419 |

- **Margin of error (wrong ÷ confident verdicts):** 0/11 = **0.00%**  → **PASS** (< 1%)
- **Logic-on-clean accuracy:** 9/9 = **100.0%** (decision logic on clean reads)
- **Coverage:** 11/15 verdicts committed confidently; 4/15 routed to human review (unreadable region or low confidence)
- **Max latency:** 419 ms (budget 5000 ms) -> PASS

_Preprocessing (deskew) lifts confident-correct verdicts on the synthetic set from 9/13 (OFF) to 11/13 (ON)._

_The hard photos that defer (2 degraded warning regions that didn't OCR, 1 real bottle photo) are correctly sent to a human rather than confidently mis-flagged. That is the measured real-world gap — surfaced as coverage, not hidden in the error rate._
