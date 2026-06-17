# PRD v1: AI-Powered Alcohol Label Verification App

- **Status:** Draft (v1) — refined via /prd interrogation, 2026-06-17
- **Author:** jayceparabellum
- **Created:** 2026-06-17
- **Source:** PVD.md (vision-from-discovery-call intake, 2026-06-17)
- **Scope discipline:** v1 only. Everything not needed to prove the one bet is
  parked in "Out of Scope."

---

## The One Bet This PRD Must Prove

> **Agents trust the tool's verdicts enough to use it instead of their own eyes —
> because it's faster and clearer.**

v1 exists to win this bet and nothing else. Three legs hold it up — **speed**
(<5s), **trust** (correct fuzzy-vs-strict matching), **usability** (the least
tech-comfortable agent succeeds with no training). Any feature that doesn't
strengthen one of those legs is out of scope for v1.

## Summary

A single-screen web app where a TTB compliance agent uploads an alcohol label
image, confirms the claimed brand name and alcohol content, and gets a clear
per-field PASS/FLAG verdict — in under five seconds — including a strict check of
the mandatory government warning, which defaults to the official 27 CFR §16.21
text so the agent never has to type it.

## Problem

TTB compliance agents spend roughly half their day on mechanical verification —
confirming the brand name, alcohol content, and government warning on a label's
artwork match the submitted application — across ~150,000 applications per year
with only 47 agents. It is high-volume, repetitive, and a poor use of expert
judgment. A prior vendor tool was abandoned because it was too slow (30–40s per
label) and too clunky; agents reverted to checking by eye. The opportunity is to
automate the rote match so fast and so clearly that agents actually adopt it.

## User Stories

1. **As a** compliance agent, **I want** to upload a label image and confirm the
   brand name and alcohol content (with the government warning pre-filled to the
   official text), **so that** I can check a label against its application without
   doing it by eye or typing boilerplate.

2. **As a** compliance agent, **I want** a clear PASS or FLAG for each field
   showing what was found on the label versus what I expected, **so that** I can
   trust the verdict at a glance and know exactly what's wrong when something is.

3. **As a** compliance agent, **I want** the brand name and alcohol content to
   match even when formatting differs (`STONE'S THROW` vs `Stone's Throw`,
   `5%` vs `5.0%`), **so that** I'm not buried in false alarms over trivial
   differences.

4. **As a** compliance agent, **I want** the government warning checked strictly —
   exact wording, all-caps `GOVERNMENT WARNING:` — **so that** a non-compliant or
   altered warning is reliably caught and never passed.

5. **As Dave (28 yrs, low-tech)**, **I want** one obvious screen with large, clear
   controls, sample labels I can try instantly, and a result in a few seconds,
   **so that** the tool is faster than my own eyes and I actually keep using it.

## Goals / Success Criteria

v1 is successful when, on a set of sample labels:

- **Speed:** every verification returns end-to-end in **< 5 seconds** (measured,
  not estimated).
- **Trust — fuzzy:** `STONE'S THROW` vs `Stone's Throw` → brand PASS; `5%` vs
  `5.0%` and a matching proof value → alcohol PASS.
- **Trust — strict:** exact §16.21 text → warning PASS; title-case
  `Government Warning`, altered wording, or missing warning → warning FAIL.
- **Honest failure:** an unreadable/very low-quality image yields a clear
  "couldn't read this image — try a clearer photo" message, **not** confidently
  wrong FLAGs.
- **Clarity:** each field shows PASS/FLAG with found-vs-expected; a non-technical
  reviewer can read the result without explanation.
- **Usability:** a first-time, low-tech user completes a verification with no
  training and no hunting for controls; sample labels are loadable in one click.
- **Deliverable:** a clean repo (README + approach/trade-off docs) and a live,
  shareable URL a reviewer can test.

## Non-goals

- **Bold-weight verification of the warning.** The warning legally must also be
  **bold**, but font weight is unreliable to detect from a photographed label via
  OCR. v1 verifies presence, exact wording, and all-caps — **not** boldness. This
  is a deliberate, documented cut, stated plainly in the README.
- Not a full COLA compliance engine (only the three named fields — see Out of
  Scope).
- Not measured on poor-quality photos or on throughput under concurrent load.

## Scope

### In scope (v1)

- **Single-label verification**, one at a time, in one web screen.
- **Inputs:** a label image upload + brand name + alcohol content (ABV or proof).
  The **expected government warning defaults to the official §16.21 text**; the
  agent confirms rather than types it.
- **One-click sample labels:** 2–3 bundled examples (one clean PASS, one bad
  warning, one ABV mismatch) so a reviewer can test the deployed URL instantly.
- **Local OCR** of the label image (no outbound ML/cloud calls).
- **Brand-name check — fuzzy/tolerant:** normalize first (lowercase, strip
  punctuation and whitespace), then compare with a **~95 similarity cutoff**.
  Because normalization runs first, `STONE'S THROW` vs `Stone's Throw` scores 100
  and PASSes; the cutoff only governs residual OCR noise.
- **Alcohol-content check — exact after normalize:** extract the number from the
  label and compare as a value; `5%`, `5.0%`, `ALC 5.0% BY VOL`, and **proof**
  (proof = 2×ABV) are equivalent to a claimed ABV, but a genuinely different
  number (5.0 vs 5.1) FLAGs.
- **Government-warning check — strict:** requires the literal all-caps
  `GOVERNMENT WARNING:` and the exact official §16.21 wording (whitespace from OCR
  line-wrapping tolerated; wording and casing not). Title-case, altered wording,
  or missing text = FAIL.
- **Bad-image handling:** if OCR yields too little usable text, return a clear
  "couldn't read this image" message instead of per-field FLAGs.
- **Results view:** per-field PASS/FLAG, each showing found-vs-expected.
- **Performance:** end-to-end result in **under 5 seconds** per label.
- **Usability:** clean, minimal, large targets, one obvious path; usable by the
  least tech-comfortable agent with no training.
- **Stateless:** no storage of labels or inputs; ephemeral processing only.
- **Deployed:** a public, shareable, testable URL (**Render via Docker**).

### Out of scope (parked — not v1)

- Batch upload of 200–300 applications. *(High-value Phase 2; v1 is single-label.)*
- Image-quality correction for angle, glare, or poor lighting. *(v1 assumes a
  reasonably legible image; it fails honestly rather than correcting.)*
- COLA workflow integration (the eventual .NET/Azure destination).
- Authentication, user roles, or permission tiers.
- Production security/compliance, PII handling, federal data retention, FedRAMP.
- Persisting results, history, audit logs, or analytics.
- Verifying any label elements beyond the three named fields (net contents,
  class/type, origin, allergens, etc.).
- Bold-text detection of the warning (see Non-goals).

## Proposed Design

### New components / modules

- **`reference`** — pins the verified official §16.21 warning string (the strict
  reference) and exposes it as the default expected value.
- **`ocr`** — wraps Tesseract (pytesseract): image bytes → extracted text; owns
  the "too little text → unreadable" signal.
- **`matching`** — three matchers: fuzzy brand (normalize → rapidfuzz ~95),
  numeric ABV/proof (exact after normalize), strict warning (exact wording + caps,
  whitespace-tolerant).
- **`verify`** — orchestrator: runs OCR, applies the three matchers, returns a
  structured per-field result (found vs expected, PASS/FLAG, or unreadable).
- **Web UI** — FastAPI routes + Jinja2 templates + vanilla CSS: an upload/confirm
  screen with sample-label buttons, and a results screen. Large targets, high
  contrast, one obvious path.

### Existing code touched

- None — greenfield repo.

### Data model changes

- None — stateless, no database, nothing persisted.

### External dependencies

- **Python / FastAPI** (web), **Uvicorn** (server), **Jinja2** (templates).
- **Tesseract OCR** system binary + **pytesseract** (local text extraction).
- **rapidfuzz** (fuzzy brand matching); **Pillow** (image loading).
- **Docker** + **Render** for the deployed public URL (bundles the Tesseract
  binary so it survives the locked-down, no-outbound environment).

## Reference: Official Government Warning (27 CFR §16.21)

Pinned verbatim (verified against Cornell LII, 2026-06-17). Strict reference
string for the warning check:

> GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink
> alcoholic beverages during pregnancy because of the risk of birth defects.
> (2) Consumption of alcoholic beverages impairs your ability to drive a car or
> operate machinery, and may cause health problems.

## Open questions

- _None outstanding._ The three prior open questions are resolved: warning input
  **defaults to §16.21 text**; deployment is **Render via Docker**; v1 **bundles
  sample labels**.

## References

- PVD.md — Project Vision Document (intake + vision)
- 27 CFR §16.21 — verified via Cornell LII (https://www.law.cornell.edu/cfr/text/27/16.21)
