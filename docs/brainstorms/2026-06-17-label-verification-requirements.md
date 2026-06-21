# Requirements: AI-Powered Alcohol Label Verification (POC)

- **Date:** 2026-06-17
- **Status:** Requirements (brainstorm output) — feeds `/scope-lock` then `/ce-plan`
- **Upstream:** `PVD.md`, `PRD.md` (was `PRD-v1.md`, since consolidated)

## Problem & Outcome

TTB compliance agents spend ~half their day manually confirming that a label's
artwork matches its application (brand, alcohol content, mandatory government
warning), across ~150,000 applications/year with 47 agents. A prior vendor tool
was abandoned for being too slow (30–40s) and too clunky. We want a standalone
proof-of-concept that does the rote match so fast and so clearly that agents
trust it over their own eyes.

**The one bet:** agents trust the tool's verdicts enough to use it instead of
their own eyes — because it's faster and clearer. Speed + trust + usability.

## Users

TTB compliance agents (~47), full tech-comfort spectrum; the binding constraint
is the least tech-comfortable agent (e.g. "Dave," 28 yrs, low-tech). Daily, core
workflow. POC is single-user, no roles.

## In Scope (what the product does)

- Single-label verification in one screen: upload a label image + claimed brand
  and alcohol content; the expected government warning defaults to the official
  27 CFR §16.21 text (agent confirms, does not type it).
- **Brand** — fuzzy/tolerant match: case/punctuation/whitespace-insensitive.
  `STONE'S THROW` matches `Stone's Throw`.
- **Alcohol content** — numeric match: `5%`, `5.0%`, `ALC 5.0% BY VOL`, and proof
  (= 2×ABV) all equal a claimed `5.0`; a genuinely different number FLAGs.
- **Government warning** — strict: exact official wording, literal all-caps
  `GOVERNMENT WARNING:`; whitespace tolerated; title-case or altered wording FAILs.
- **Per-field PASS/FLAG** result showing found-vs-expected, readable by a
  non-technical reviewer.
- **Honest failure:** an unreadable image returns "couldn't read — try a clearer
  photo," not confidently-wrong flags.
- **3 bundled sample labels** (clean PASS / ABV mismatch / bad warning) for
  one-click testing of the deployed URL.
- **Deployed, shareable public URL.**

## Success Criteria

- **Latency:** end-to-end verification < 5 seconds per label (measured).
- **Accuracy:** **< 1% margin of error on the decision logic given correctly-read
  text** — i.e., the matchers, evaluated on correct OCR text, decide PASS/FLAG
  correctly >99% of the time (unit-testable). See Assumptions for the OCR carve-out.
- **Trust cases (must hold):** `STONE'S THROW` vs `Stone's Throw` → brand PASS;
  `5%` vs `5.0%` / matching proof → alcohol PASS; exact §16.21 → warning PASS;
  title-case `Government Warning` / altered / missing → warning FAIL.
- **Usability:** a first-time, low-tech user completes a verification with no
  training and no hunting for controls.
- **Deliverable:** clean repo + README (approach, tools, trade-offs) + live URL.

## Key Decision: How "< 1% margin of error" is defined

Error is scoped to the **matching/decision logic on correctly-read text**, not to
the whole OCR pipeline. Rationale: OCR on real photos is inherently imperfect; a
strict warning check on a blurry label will misread characters no matter how good
the logic is. Folding OCR legibility into the error budget would make the bar
both unmeasurable and unachievable for a POC. So:

- The <1% bar is verified by unit tests over the matchers with known text inputs.
- OCR misreads on poor images are a **documented limitation**, surfaced to the
  user as an honest "couldn't read" rather than a wrong verdict where possible.
- (Rejected alternatives: whole-pipeline <1% — too ambitious for a POC;
  confidence-gated "needs human review" abstention — deferred to Phase 2.)

## Scope Boundaries — Deferred (not this POC)

- Batch upload of 200–300 labels.
- Image-quality correction (angle/glare/lighting).
- Confidence-gated "needs human review" abstention.
- COLA integration, auth/roles, persistence/history, FedRAMP/PII posture.

## Outside this product's identity

- Not a full COLA compliance engine — only brand, ABV, and warning are checked
  (not net contents, class/type, origin, allergens, etc.).
- **Bold-weight verification of the warning is explicitly out** — font weight is
  unreliable to detect from a photo via OCR; documented in the README.

## Dependencies / Assumptions

- Deployment environment blocks outbound ML/cloud APIs → processing must be local
  (drives the technical direction toward local OCR; details are `/ce-plan`'s job).
- POC handles no real PII; nothing is stored; processing is ephemeral.
- Images are assumed reasonably legible; the POC fails honestly rather than
  correcting poor images.

## Open Questions

- _None blocking._ Error-margin definition resolved (logic-scoped). Deploy target,
  module layout, and library choices are implementation decisions for `/ce-plan`.
