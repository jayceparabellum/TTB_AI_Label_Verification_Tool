# Real clean labels — false-positive baseline

Drop **genuinely compliant** label images here (the kind that should PASS all three
checks: brand, alcohol content, government warning). The eval runner
(`python eval/run_eval.py`) picks them up automatically, scores them in the board,
and computes the **false-positive rate** — how often a clean label is *confidently
flagged*. This is the corpus the synthetic samples can't be: real submitted-label
artwork, which is where the "clean labels being flagged" defect actually lives.

## How to add a label

1. Put the image in this folder: `.png`, `.jpg`, or `.jpeg`.
2. Add a sidecar text file with the **same name** and a `.txt` extension giving the
   claimed application data:

   ```
   <filename>.txt   →   Brand Name|ABV
   ```

   Example — `sunny_vale.jpg` + `sunny_vale.txt`:
   ```
   Sunny Vale|12.5
   ```

   - `brand` is the brand name exactly as on the COLA application.
   - `abv` is the claimed alcohol content as a number (e.g. `5.0`, `12.5`).
   - These labels are **known-compliant**, so the TRUE verdict is PASS on all three
     fields — you don't specify per-field verdicts (that's automatic here).
   - Lines starting with `#` are comments.

## What it measures

- **False-positive rate** = compliant labels that got a *confident FLAG* ÷ all
  compliant labels. Goal: drive this toward 0. A compliant-but-hard-to-read label
  that **safely defers to NEEDS REVIEW is not** a false positive.
- These cases also let us **calibrate** the government-warning thresholds
  (`WARNING_SIMILARITY_THRESHOLD`, `WARNING_REVIEW_FLOOR` in `app/matching.py`) so
  compliant reads PASS, genuinely-altered ones FLAG, and the noisy middle defers.

Files here (other than this README) are local eval data and need not be committed.
