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
pytest                    # 27 unit + end-to-end tests
python eval/run_eval.py   # accuracy + latency report -> eval/REPORT.md
```

The eval harness reports **two honest numbers** instead of one round figure:

- **Logic-on-clean accuracy — 100%** (9/9 field decisions). The decision logic on
  correctly-read text; this is the deterministic core and the basis for the
  `<1%`-error target.
- **End-to-end accuracy — 57%** (4/7 cases), full OCR + matching *including
  degraded photos* (rotation, blur, JPEG noise, low contrast). All 3 clean cases
  pass; on the 4 degraded cases, **brand and ABV still pass every time** — only
  the deliberately-strict warning check misses when OCR drops a character. That is
  the documented trade-off, measured rather than hidden, not a logic error.

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
- **Single label at a time.** Batch upload, image-quality correction, a
  "needs human review" confidence state, COLA integration, and auth are all
  deliberately out of scope for this POC (candidate next steps).
- **OCR is CPU-bound, so the host's CPU sets the latency.** On a normal CPU the
  full verify is ~200 ms (well under the 5 s budget). Tesseract is tuned for
  constrained hosts (`--psm 6`, single OpenMP thread). Note that a heavily
  throttled instance (e.g. Render's free 0.1-CPU tier) can push a single OCR
  call to ~20 s — use at least ~0.5–1 CPU (Render Starter/Standard or equivalent)
  to keep verifications under 5 s.

---

## License

[MIT](LICENSE) © 2026 Jayce Parabellum
