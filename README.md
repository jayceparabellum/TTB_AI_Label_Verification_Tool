# TTB AI Label Verification Tool

A proof-of-concept web app for TTB compliance agents. Upload a label photo plus
the claimed application data (brand name, alcohol content); the app reads the
label locally and returns a clear **PASS / FLAG** for each of three checks —
brand name, alcohol content, and the mandatory government warning — in under a
second.

This is a standalone POC. It is **not** integrated with COLA or any government
system, stores nothing, and handles no real PII.

**🔗 Live demo:** https://ttb-label-verification-9q01.onrender.com — upload a
label, or try one of the three bundled samples with one click.

![Demo: upload a label, get a per-field PASS/FLAG verdict in well under a second](docs/media/demo.gif)

<sub>Upload screen → a clean label PASSes all three checks → a non-compliant
label is FLAGGED. ([upload](docs/media/home.png) · [PASS](docs/media/result-pass.png) · [FLAG](docs/media/result-flag.png) stills)</sub>

---

## What it checks

| Field | Strategy | Why |
|-------|----------|-----|
| **Brand name** | Fuzzy / tolerant | Formatting differences are not violations. `STONE'S THROW` matches `Stone's Throw`. Normalize (lowercase, strip punctuation/whitespace) then compare at a 95 similarity cutoff. |
| **Alcohol content** | Numeric | `5%`, `5.0%`, `ALC 5.0% BY VOL`, and proof (`10 PROOF` = 5% ABV) all match a claimed `5.0`. A genuinely different number FLAGs. |
| **Government warning** | Strict, exact | Requires the literal all-caps `GOVERNMENT WARNING:` and the exact 27 CFR §16.21 wording. Title case (`Government Warning`), altered wording, or missing text = FAIL. Only whitespace (OCR line-wrapping) is tolerated. |

The expected warning defaults to the official §16.21 text, so an agent never types it.

---

## Quick start

Requires Python 3.12 and Tesseract OCR.

```bash
# 1. Tesseract (system binary)
sudo apt-get install -y tesseract-ocr        # Debian/Ubuntu
# macOS: brew install tesseract

# 2. Python deps
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Generate the bundled sample labels
python scripts/generate_samples.py

# 4. Run
uvicorn app.main:app --reload
# open http://127.0.0.1:8000
```

No root for the Tesseract install? You can extract the `.deb` into a local prefix
and point the app at it — `app/ocr.py` auto-detects a Tesseract under
`~/.local/tess` when none is on `PATH`.

---

## Tests and evaluation

```bash
pytest                    # 69 unit + end-to-end tests
python eval/run_eval.py   # accuracy + latency report -> eval/REPORT.md
```

The eval harness reports **two honest numbers** instead of one round figure:

- **Logic-on-clean accuracy — 100%** (9/9 field decisions). The decision logic on
  correctly-read text; this is the deterministic core and the basis for the
  `<1%`-error target.
- **End-to-end accuracy — 69%** (9/13 cases), full OCR + matching *including
  degraded photos* across 10 real-world failure modes (rotation, blur, JPEG,
  low/uneven lighting, perspective, glare, shadow, sensor noise, blur+rotate).
  An OpenCV deskew stage before OCR lifts this from 54% (**+15 pts**, ablation-tuned
  in `eval/ablate.py`). All 3 clean cases pass and **brand and ABV pass on every
  degraded case** — only the deliberately-strict warning check misses when OCR
  drops a character on the hardest reads. That is the documented trade-off,
  measured rather than hidden, not a logic error.

Per-failure-mode breakdown on the degraded set (compliant label, so the true
verdict for every field is PASS — a ✗ is an OCR misread, not a wrong decision):

| Degraded photo (failure mode) | Brand | ABV | Warning | Verdict |
|-------------------------------|:-----:|:---:|:-------:|---------|
| 5° rotation                   |   ✓   |  ✓  |    ✗    | flag\*  |
| 8° rotation (heavy)           |   ✓   |  ✓  |    ✓    | **pass** |
| Gaussian blur                 |   ✓   |  ✓  |    ✗    | flag\*  |
| JPEG compression (q30)        |   ✓   |  ✓  |    ✗    | flag\*  |
| Low contrast                  |   ✓   |  ✓  |    ✓    | **pass** |
| Perspective / keystone        |   ✓   |  ✓  |    ✓    | **pass** |
| Glare / overexposure          |   ✓   |  ✓  |    ✓    | **pass** |
| Shadow / uneven lighting      |   ✓   |  ✓  |    ✗    | flag\*  |
| Sensor noise                  |   ✓   |  ✓  |    ✓    | **pass** |
| Blur + rotation (compound)    |   ✓   |  ✓  |    ✓    | **pass** |

**6/10 degraded photos fully pass; brand and ABV are read correctly on all 10.**
The four `flag\*` rows are *warning-only* misses where OCR dropped a character in
the long §16.21 text — the strict matcher then conservatively flags for human
review rather than passing a possibly-wrong label. Regenerate this table anytime
with `python eval/run_eval.py` (writes `eval/REPORT.md`).

Latency stays far under the 5-second budget: **~80–270 ms server compute locally**,
and **~550–750 ms on the live Render Starter instance** (~1 s round-trip including
network).

---

## Approach & tools

- **FastAPI + Jinja2 + vanilla CSS**, server-rendered. One upload screen, one
  results screen, large targets — no JS build step. Built to be usable by the
  least tech-comfortable agent.
- **Tesseract OCR (pytesseract)**, fully local. The target deployment blocks
  outbound traffic to external ML/cloud APIs, so OCR runs in-process. Tesseract
  easily meets the latency budget on a legible label.
- **rapidfuzz** for fuzzy brand matching; plain numeric logic for ABV; exact
  string logic for the warning.
- **Stateless** — nothing is persisted; each request is processed and discarded.

```
app/
  reference.py   # pinned official §16.21 warning text
  ocr.py         # Tesseract wrapper + readability gate
  matching.py    # fuzzy brand, numeric ABV, strict warning
  verify.py      # orchestrator: OCR -> matchers -> result
  models.py      # VerificationResult
  main.py        # FastAPI routes + templates
eval/            # labeled set + honest accuracy/latency report
tests/           # unit + end-to-end tests
```

---

## Deploy

Docker bundles the Tesseract binary so it survives a locked-down runtime.

```bash
docker build -t ttb-label-verification .
docker run -p 8000:8000 ttb-label-verification
```

`render.yaml` declares a Docker web service for one-click deploy on Render;
`scripts/deploy_render.sh` is a one-command deploy once `render login` is done.
The live instance runs on Render's **Starter** plan (free tier's 0.1 CPU is too
throttled for OCR — see the latency note below). Health check at `/health`.

---

## Trade-offs & known limitations

- **Bold-text detection is intentionally skipped.** The warning legally must also
  be **bold**, but font weight is unreliable to detect from a photographed label
  via OCR. We verify presence, exact wording, and ALL CAPS — not boldness. This is
  a deliberate, documented cut, not an oversight.
- **Accuracy is scoped honestly.** The `<1%`-error target applies to the decision
  logic on correctly-read text (measured 100%). OCR legibility on poor photos is a
  separate, *measured* limitation (see the eval report), surfaced to the user as a
  friendly "couldn't read this image" where possible rather than a wrong verdict.
- **Strict warning matching is deliberately unforgiving.** It will FLAG a compliant
  label if OCR badly mangles the warning text. This is faithful to the requirement
  that the warning be exact, at the cost of some false flags on low-quality photos.
- **Real-world bottle photos often read poorly — and the app says so rather than
  guessing.** A glare-lit phone photo (small label in a busy frame, curved glass)
  can OCR to near-garbage. Two safeguards keep that honest: (1) when OCR confidence
  is low the verdict is **NEEDS REVIEW — low confidence read**, not a confident
  PASS/FAIL; (2) each field only reports a match it actually earned — the fuzzy
  brand matcher requires a genuine similarity score, so garbled text scores low and
  FLAGs instead of falsely passing. (A real Jack Daniel's bottle photo, for example,
  reads at ~37% confidence: ABV `40%` matches, but the brand and warning correctly
  FLAG and the whole result is sent to human review.) The bundled samples and most
  of the eval set are clean/degraded *flat* labels — expect more NEEDS-REVIEW
  outcomes on real bottle photography.
- **Out of scope for this POC.** COLA / government-system integration and
  authentication are deliberately not built (candidate next steps). Batch
  verification and the low-confidence "needs review" state — originally deferred —
  are now implemented.
- **OCR is CPU-bound, so the host's CPU sets the latency.** On a normal CPU the
  full verify is ~200 ms (well under the 5 s budget). Tesseract is tuned for
  constrained hosts (`--psm 6`, single OpenMP thread). Note that a heavily
  throttled instance (e.g. Render's free 0.1-CPU tier) can push a single OCR
  call to ~20 s — use at least ~0.5–1 CPU (Render Starter/Standard or equivalent)
  to keep verifications under 5 s.

---

## License

[MIT](LICENSE) © 2026 Jayce Parabellum
