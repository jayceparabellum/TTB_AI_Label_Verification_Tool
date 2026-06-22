# Synthetic clean labels — calibration cohort

This folder holds **generated, compliant** label images used to calibrate the
government-warning thresholds and to confirm the system never *confidently FLAGs* a
clean label. They are produced at eval time by `_make_synthetic_clean()` in
`eval/run_eval.py` (varied brand/ABV, warning print size, background tint, and mild
degradation — all carrying the full ALL-CAPS §16.21 warning, so the TRUE verdict is
all-PASS). The `.png` files here are regenerated each run and are **not** committed
(only this README is).

## Synthetic — not a substitute for `real_clean/`

These are idealized renders, not real submitted-label photographs. They give the
**false-positive metric** signal across more variety than the three fixed in-scope
labels can, but they cannot exhibit the real-world false-positive defect (glare,
curvature, thin metallic print, odd fonts) that only real artwork shows. That gap is
deliberately kept honest in `../real_clean/`, whose count stays 0 until **real**
images are added there. Do not move synthetic renders into `real_clean/`.

## What it guards

`tests/test_synthetic_clean_calibration.py` asserts every label in this cohort either
PASSes or safely defers to NEEDS REVIEW — **never** a confident FLAG on a compliant
label. A future threshold change that starts false-flagging clean labels fails that
test in CI.
