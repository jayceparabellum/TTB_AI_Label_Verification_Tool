# TTB AI Label Verification Tool

[![CI](https://github.com/jayceparabellum/TTB_AI_Label_Verification_Tool/actions/workflows/ci.yml/badge.svg)](https://github.com/jayceparabellum/TTB_AI_Label_Verification_Tool/actions/workflows/ci.yml)

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

## Sample data

Every input surface ships with ready-to-run sample data so you can try the app
without supplying your own labels. The files are served as plain static assets,
so they download from any running instance (including the [live demo](https://ttb-label-verification-9q01.onrender.com))
with no account or login.

| Surface | What to download | Path on the app |
|---------|------------------|-----------------|
| **Single label** (`/`) | Three generated labels — a clean PASS, a wrong-ABV FLAG, a bad-warning FLAG | `/static/samples/clean_pass.png`, `/static/samples/abv_mismatch.png`, `/static/samples/bad_warning.png` |
| **Batch** (`/batch`) | A ready-to-run batch — 25 real alcohol labels (`.zip`) + a matching CSV | `/static/alcohol_labels.zip`, `/static/batch-template-filled.csv` |
| **Batch** (`/batch`) | A blank CSV template to fill in for your own batch | `/static/batch-template.csv` |

**From the browser (easiest).** On the running app, the samples are one click away:

- On the home page (`/`), use the **"Verify the … sample"** chips to run a single
  sample, or right-click → *Save image as* on any sample thumbnail to download it.
- On the batch page (`/batch`), scroll to the **"Try it with sample data"** card and
  click **⬇ Sample labels (.zip, 25 images)** and **⬇ Matching CSV** — then upload
  both back into the form above to see a full 25-label batch run end to end.

**From the command line.** Point the host at your instance (defaults below use the
local dev server):

```bash
HOST=http://127.0.0.1:8000   # or https://ttb-label-verification-9q01.onrender.com

# batch sample (zip of 25 labels + the CSV that matches them)
curl -O "$HOST/static/alcohol_labels.zip"
curl -O "$HOST/static/batch-template-filled.csv"

# blank batch template
curl -O "$HOST/static/batch-template.csv"

# single-label samples
for f in clean_pass abv_mismatch bad_warning; do curl -O "$HOST/static/samples/$f.png"; done
```

The 25-label zip and its CSV are a matched, self-consistent batch (every CSV row
names a file in the zip and vice-versa, within the 25-label cap), so uploading the
two together verifies cleanly. The single-label samples are generated from
`scripts/generate_samples.py` (run automatically in [Quick start](#quick-start)
below); the batch assets ship committed under `app/static/`.

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

The four steps above are **all you need** for the full verifier, the batch UI, the
pop-out assistant, and BM25 regulatory lookup. Two layers are **optional** and
turn on only when their dependency is present (otherwise they degrade gracefully):

```bash
# (optional) the conversational LLM — a local Ollama 3B model
bash scripts/setup_ollama.sh                 # pulls llama3.2:3b; chat works once it's up
# (optional) dense RAG retrieval — BGE-small embeddings (else BM25-only)
pip install sentence-transformers            # then RAG_DENSE=auto enables it

# run the tests + the evaluations
pytest                                        # 342 passing
python eval/run_eval.py                       # verifier decision board -> eval/REPORT.md
python eval/run_rag_eval.py                   # RAG hit-rate / faithfulness / citation
python eval/run_agent_eval.py gate            # agent-behavior gate (replay) -> eval/AGENT_REPORT.md
```

---

## Tests and evaluation

```bash
pytest                    # 342 passing unit + end-to-end tests
python eval/run_eval.py   # goal metrics + latency report -> eval/REPORT.md
```

The goal is **< 1% margin of error, < 5 s latency**. The board scores the system on
its **intended input** — the label image an agent submits with a COLA application —
across 16 cases: 3 clean labels, 10 degraded variations (real photo/scan artifacts),
and 3 varied product-label images. Each case is either a **confident verdict** or a
**safe deferral**; the only failure is a *confident wrong* verdict.

- **Confident coverage — 16/16 = 100%** — the system commits a verdict on every
  in-scope case.
- **Decision correctness — 16/16 = 100%**, **zero wrong verdicts**.
- **Margin of error — 0.00%** (0 wrong of 16 confident verdicts). **Meets the < 1% goal.**
- **Logic-on-clean accuracy — 100%** (9/9 field decisions on cleanly-read text).
- **Max latency — ~290 ms** (budget 5000 ms), well under the bar.

Per-case outcomes on the degraded set (a ✗ cell is an OCR misread; the *outcome*
is the decision the system made about it — all now confident-correct):

| Degraded photo (failure mode) | Brand | ABV | Warning | Outcome |
|-------------------------------|:-----:|:---:|:-------:|---------|
| 5° rotation                   |   ✓   |  ✓  |    ✓    | ✅ correct |
| 8° rotation (heavy)           |   ✓   |  ✓  |    ✓    | ✅ correct |
| Gaussian blur                 |   ✓   |  ✓  |    ✓    | ✅ correct |
| JPEG compression (q30)        |   ✓   |  ✓  |    ✓    | ✅ correct |
| Low contrast                  |   ✓   |  ✓  |    ✓    | ✅ correct |
| Perspective / keystone        |   ✓   |  ✓  |    ✓    | ✅ correct |
| Glare / overexposure          |   ✓   |  ✓  |    ✓    | ✅ correct |
| Shadow / uneven lighting      |   ✓   |  ✓  |    ✓    | ✅ correct |
| Sensor noise                  |   ✓   |  ✓  |    ✓    | ✅ correct |
| Blur + rotation (compound)    |   ✓   |  ✓  |    ✓    | ✅ correct |

**10/10 degraded photos now get a confident-correct verdict.** Three preprocessing
steps and a tolerant-but-strict warning matcher make this honest rather than lucky:
(1) **deskew** straightens rotated labels, **CLAHE contrast** normalizes uneven
lighting (recovers a brand whose start was lost to a left-side shadow), and
**upscaling** enlarges low-res uploads so a heavily-compressed image's warning reads
(jpeg q30 went from ~73% to ~93% confidence); (2) the warning check is **strict on
wording/casing but tolerant of OCR noise** — it fuzzy-matches the §16.21 body
(compliant reads score ≥ 99.6%) instead of demanding all 283 characters verbatim, so
a one-character OCR slip no longer false-FLAGs a compliant label.

### Out-of-scope: real-world bottle photography

The eval also keeps three **real phone photos of bottles** (Jack Daniel's, Cîroc,
Grey Goose, in `eval/images/real/`) as a *stress test* — glare, reflections, dark
backgrounds, thin metallic label text. This is **not** the product's input (a
submitted label image), and local Tesseract (a hard requirement) can't read them.
The point: all three **safely defer to human review** and **none produces a wrong
verdict** — the system declines to guess rather than mis-flagging a compliant label.
They are reported separately and not counted in the board above. Drop more photos
into `eval/images/real/` with a `brand|abv|exp_brand,exp_alcohol,exp_warning`
sidecar to extend the stress set.

Latency stays far under the 5-second budget: **~150–300 ms server compute locally**,
and **~550–750 ms on the live Render Starter instance** (~1 s round-trip including
network).

### Agent behavior eval (record → replay)

The deterministic core and RAG each have an eval; the **agent layer on top** has its
own, with a **record(live) → gate(replay)** split so the gate is deterministic, free,
and CI-stable. It checks the agent's load-bearing invariants: it reports the
deterministic tool's verdict **verbatim** (never its own pass/fail), routes to the
right tool, never runs a WRITE without the **confirm gate** firing, and RAG
**cites-or-refuses**. A small record-time **LLM-judge** scores each explanation
(faithfulness + clarity, 1–5) and the scores are threshold-checked at gate time.

```bash
# gate (FREE, CI-safe) — replays committed snapshots, grades invariants, no LLM.
# Writes eval/AGENT_REPORT.md and exits non-zero on any violation.
python eval/run_agent_eval.py gate

# record (LIVE, SPENDS ANTHROPIC CREDITS) — drives the agent against cloud Claude,
# captures transcripts + confirm-gate interrupts, scores explanations, and writes
# eval/agent_snapshots/*.json. Manual + infrequent; re-run after any agent/ change.
LLM_BACKEND=anthropic ANTHROPIC_API_KEY=sk-... python eval/run_agent_eval.py record
```

**Workflow:** `record` is the only step that touches a model and spends credits — it
bakes everything the gate needs (transcript, deterministic ground truth, judge
scores) into committed JSON. `gate` is pure replay over that JSON: it never calls a
model, so it runs free in CI on every change. Re-record when you change `agent/` or
the prompts; the gate otherwise grades stale behavior. The repo ships
`eval/agent_snapshots/` empty (recording is a deliberate, credit-spending step); the
gate works on whatever snapshots are present and reports *no snapshots yet* on an
empty set. To prove the gate has teeth, tamper a recorded snapshot (e.g. change a
narrated PASS to a verdict the tool didn't return) and the gate fails loudly.

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
agent/           # Layer 2 — LangGraph chat agent (graph, tools, confirm gate, audit)
rag/             # Layer 3 — local citation-grounded knowledge layer
tests/           # unit + end-to-end tests
```

---

## AI assistant (Layer 2) + regulatory knowledge (Layer 3)

On top of the deterministic core, an additive **conversational agent** — reachable
from the `/chat` page or a **pop-out widget docked bottom-right of every page**
(minimizable; the conversation persists across navigation) — lets an agent drive
every feature in plain language, and a local **RAG knowledge layer** answers
regulatory questions with citations. The governing rule everywhere:
**the LLM orchestrates and explains; it never adjudicates.** Pass/fail is always the
deterministic core's; RAG grounds explanations but gets no vote; a human commits
every change.

- **LangGraph agent, local model.** Tools *wrap* the core (single source of truth):
  `verify_label` returns the identical verdict to the button UI. The model is local
  **Ollama** (`langchain-ollama`); a `SqliteSaver` checkpointer keys session memory
  and interrupt/resume by `thread_id`. Streaming SSE chat with **visible tool steps**;
  vanilla JS, no build step. The button UI stays the primary, always-available path.
- **In-chat omni-ingest — verify your own labels without leaving the chat.** Bytes
  arrive via a companion `POST /agent/upload` (multipart, returns ids) so the SSE turn
  stays simple; tools read the bytes from the session by id — **never** from model
  args — so the deterministic verdict can't be substituted or hallucinated. Three
  ingest paths, each parity-equal to its button-UI counterpart:
  - **Image** — drag/drop, pick, or **paste** (clipboard screenshot) a label, then
    give the claimed brand/ABV → `verify_label`. A "Verify this label" chip auto-suggests.
  - **Text** — paste or type the label wording → `verify_text` (wraps `reverify_text`).
  - **Batch** — attach a mapping **CSV + images, or a `.zip` of up to 25 label photos**
    (unzipped server-side, in memory), Approve at the confirm gate → `batch_verify` over
    `run_batch` (25-label cap), streamed summary + flagged list + a **downloadable results
    CSV**. The same `.zip` ingest works on the dedicated `/batch` page; both surfaces share
    one extractor (`app/ingest.py`), so behavior is identical. Over-25 zips are **rejected**
    with a clear message rather than silently truncated.

  Uploads live **in-process only** (no disk, no PII at rest), are bounded by per-file
  (10 MB) and per-thread (50 MB) caps, and are **evicted** when the chat is closed
  (`/agent/reset`). The dedicated `/`, `/text`, `/batch` pages stay primary and untouched.
- **Human-in-the-loop confirm gate.** Read tools flow through; before any **write**
  (`override_result`, `manual_fallback`, `batch_verify`) the graph calls `interrupt()`
  and resumes only on an explicit human **Approve** — the agent can never auto-commit.
  Every write is recorded to an **append-only audit log** (who/what/when/why).
- **Citation-grounded RAG, cite-or-refuse.** Hybrid retrieval — BM25 fused with
  dense **BGE-small** embeddings via reciprocal-rank fusion (`rag/dense.py`; BM25-only
  until `pip install sentence-transformers`, then auto-on via `RAG_DENSE`) — over a
  committed, citation-tagged 27 CFR corpus spanning the health warning (Part 16) and
  per-commodity labeling for wine (Part 4), distilled spirits (Part 5), and malt
  beverages (Part 7). `regulatory_lookup` and
  `explain_flag` answer **only** from retrieved chunks, always cite the controlling
  section, and **refuse** ("not found in the regulations on file") when unsupported —
  never reciting regulation from memory. RAG eval: hit-rate 100%, faithfulness 100%,
  citation 100% across 14 golden cases (`eval/run_rag_eval.py`).
- **Fully offline.** No outbound calls at runtime (local Tesseract, local BM25, local
  Ollama) — proven by `tests/test_offline.py`, which blocks outbound sockets and runs
  the verify + RAG paths.

> The deterministic 5 s SLA is unaffected: verification is a single tool call **off**
> the model path, and RAG stays off the hot path. When the model is unavailable, the
> chat degrades gracefully and the button verifier keeps working.

---

## Deploy

Docker bundles the Tesseract binary so it survives a locked-down runtime. The
standard image ships all three layers — the button verifier plus the `/chat`
panel and the BM25 RAG corpus — so the chat works wherever it's deployed; the LLM
(Ollama) and dense embeddings are simply absent on a lean host, so chat degrades
gracefully and RAG runs BM25-only.

```bash
docker build -t ttb-label-verification .
docker run -p 8000:8000 ttb-label-verification
```

`render.yaml` declares a Docker web service for one-click deploy on Render. The
live instance runs in the **`ttb-label-verification` Render project** (Production
environment) on the **Starter** plan — the free tier's 0.1 CPU is too throttled for
OCR (see the latency note below). It **auto-deploys on push to `main`**; you can also
trigger a deploy from the Render dashboard or with `scripts/deploy_render.sh` (after
`render login`). Health check at `/health`; live URL at the top of this README.

The **conversational agent** needs a chat model. By default it uses a **local
Ollama** model (fully offline) — which the Starter host can't run, so there the
chat would degrade gracefully and the button verifier is the path. For a deployed
host with no local model, set **`LLM_BACKEND=anthropic`** plus an **`ANTHROPIC_API_KEY`**
secret and the agent uses **Claude** via the cloud API (`agent/llm.py`); the live
demo runs this way. This is an explicit, opt-in relaxation of "fully offline" for
the deployed demo only — local and air-gapped runs leave `LLM_BACKEND` unset and
stay 100% offline.

To instead run the full three-layer stack (verifier + agent + RAG) **offline** on
one ~4 GB box, use the dedicated agent image. It bundles Ollama and **bakes the model into the image
at build time**, so the running container makes zero outbound calls:

```bash
docker build -f Dockerfile.agent -t ttb-label-agent .   # add --build-arg OLLAMA_MODEL=qwen2.5:3b-instruct to swap
docker run -p 8000:8000 -v ttb_agent_data:/app/.agent_data ttb-label-agent
```

The volume persists the append-only audit log and session checkpoints across
restarts. RAG retrieval is BM25-only by default; the dense BGE-small/Chroma
backend is host-deferred (uncomment the `pip install` in `Dockerfile.agent`).
Everything stays local — no outbound calls at request time.

---

## Assumptions

The build rests on these explicit assumptions — they shape what the tool does and
does not do:

- **Input is a submitted label image**, not a shelf photo of a bottle. The product's
  input is the legible, roughly flat label an agent files with a COLA application;
  glare/reflection-heavy bottle photography is a documented stress set, not the target.
- **Brand, alcohol content, and the §16.21 warning are the always-on adjudicated
  fields.** **Net contents** and **class/type** are also adjudicated when a claimed
  value is supplied — across every surface: the single-label image/text forms, the
  batch CSV (optional `net_contents`/`class_type` columns), and the chat verify tools.
  Net contents is a metric numeric match; class/type is a fuzzy label-presence check
  (NOT standards-of-identity correctness). Each uses a safe PASS / FLAG / defer-to-
  NEEDS-REVIEW verdict and is never flagged when omitted. Producer and country remain
  best-effort raw text, clearly marked "not adjudicated."
- **Local Tesseract is a hard constraint** (the deployment blocks outbound ML/cloud
  calls), so OCR quality is Tesseract's; an unreadable field **safely defers** to a
  human rather than guessing.
- **The official §16.21 text is the expected warning by default**, so an agent never
  types it; only whitespace/line-wrap differences are tolerated, casing/wording are not.
- **Runtime is fully offline.** Models and the regulatory corpus are provisioned at
  build time; nothing leaves the network when a request is served.
- **The regulatory corpus is a curated, citation-verified excerpt** of 27 CFR
  (Parts 4/5/7/16) — section numbers verified against live eCFR (2026-06-10), chunk
  wording a faithful summary — not a full live eCFR ingest.
- **The LLM and RAG never adjudicate.** The deterministic core owns every pass/fail; a
  human approves every write; the agent can never auto-submit a compliance approval.
- **POC boundaries.** No COLA/government-system integration, no auth, no real PII;
  verify is stateless. The audit log + chat checkpoints are local SQLite (ephemeral on
  the free host).
- **Benchmark user is the least tech-comfortable reviewer** — hence large targets
  (≥44px), one obvious action per screen, and a button path that always works even when
  the assistant or a model is unavailable.

---

## Trade-offs & known limitations

> **Master-brief Phase-1 mapping.** This repo *is* the brief's Layer-1
> verification core. The function names differ from the brief's pseudo-names
> (`extract_text`/`extract_text_data` ≈ `extract_fields`; `match_brand` +
> `match_alcohol_content` ≈ `fuzzy_match`; `match_government_warning` ≈
> `verify_warning_strict`), and OCR structures the three verdict-bearing fields
> (brand, ABV, warning) rather than the brief's seven. **One deliberate deviation:**
> the brief specifies a *strict, word-for-word* warning match, but the implemented
> matcher is a **high-threshold fuzzy match (≥ 99% similarity)** anchored on the
> ALL-CAPS `GOVERNMENT WARNING:` header. This was a measured choice — exact-substring
> matching false-flagged compliant labels whenever OCR dropped a single character in
> the 283-char §16.21 block; the fuzzy threshold tolerates that noise while still
> failing Title-case, missing, or genuinely-altered warnings (see `eval/REPORT.md`,
> 0% confident-error margin). The agent + RAG layers (Phases 2–3) are planned in
> `docs/plans/2026-06-18-001-feat-conversational-agent-rag-plan.md` and not yet built.

- **Bold-text detection is intentionally skipped.** The warning legally must also
  be **bold**, but font weight is unreliable to detect from a photographed label
  via OCR. We verify presence, exact wording, and ALL CAPS — not boldness. This is
  a deliberate, documented cut, not an oversight.
- **Accuracy is scoped to the goal's definition.** `<1%` margin of error is
  measured on the verdicts the system *commits to*: **0 wrong of 11 confident
  verdicts (0.00%)**, with the decision logic on clean text at 100%. Hard reads are
  deferred to human review (reported as *coverage*), not counted as errors or
  hidden — see the eval report.
- **Warning matching is strict on wording and casing, but tolerant of OCR noise.**
  It requires the official §16.21 text in ALL CAPS and FLAGs Title-case or altered
  wording — but it *fuzzy-matches the body* (compliant reads score ≥ 99.6%), so a
  one-character OCR slip no longer false-FLAGs a compliant label. When the warning
  region can't be read at all, it **defers to NEEDS REVIEW** rather than asserting
  non-compliance. (A genuinely-missing warning on a pristine image therefore also
  defers — a conservative, never-false-pass choice; region-aware confidence to
  separate "absent" from "unreadable" is a candidate next step.)
- **Real-world bottle photos often read poorly — and the app says so rather than
  guessing.** A glare-lit phone photo (small label in a busy frame, curved glass)
  can OCR to near-garbage. Two safeguards keep that honest: (1) when OCR confidence
  is low the verdict is **NEEDS REVIEW — low confidence read**, not a confident
  PASS/FAIL; (2) each field only reports a match it actually earned — the fuzzy
  brand matcher requires a genuine similarity score, so garbled text scores low and
  FLAGs instead of falsely passing. (A real Cîroc or Grey Goose bottle photo, for
  example, reads at ~30–40% confidence on its thin reflective label, so the whole
  result defers to NEEDS REVIEW rather than guessing.) The bundled samples and most
  of the eval set are clean/degraded *flat* labels — expect more NEEDS-REVIEW
  outcomes on real bottle photography.
- **Agent/RAG: model hosting is a deliberate trade.** (1) The chat agent needs a
  chat model: **local Ollama** by default (fully offline, needs a ~4 GB host —
  `bash scripts/setup_ollama.sh`), **or** cloud **Claude** on a lean deployed host
  via `LLM_BACKEND=anthropic` + an `ANTHROPIC_API_KEY` secret (the live demo). Cloud
  mode is an explicit opt-in that relaxes "fully offline" for that deploy only. (2)
  RAG retrieval runs **BM25-only by default**;
  the **dense BGE-small** backend (`rag/dense.py`, fused with BM25 via RRF) is fully
  implemented and turns on automatically once `pip install sentence-transformers`
  makes the embedder importable (`RAG_DENSE=auto`). The model downloads once and then
  runs offline; at this corpus size the vector store defaults to an exact in-memory
  numpy cosine, rebuilt at startup. For a persistent store that survives restarts,
  set `RAG_DENSE_STORE=chroma` (`pip install chromadb`) — embeddings are computed once
  and reused, telemetry disabled so it stays offline. BM25 is strong for term-heavy
  regulatory queries; dense adds synonym/paraphrase recall.
- **RAG corpus is a curated excerpt, not the full live eCFR.** The committed corpus
  is 27 CFR Part 16 + labeling slices of Parts 4 (wine), 5 (distilled spirits), and 7
  (malt beverages), citation-accurate and offline; §16.21 is verbatim. All section
  **numbers are verified against the live eCFR** structure API (title 27, issue date
  2026-06-10); chunk wording is a faithful conservative summary, so confirm exact text
  against each `source_url` before operational use. The full live ingest of
  Parts 4/5/7/16 + the TTB Beverage Alcohol Manual is the deferred build-time step. Every chunk carries a `source_url` to verify
  against eCFR.
- **Out of scope for this POC.** COLA / government-system integration and
  authentication are deliberately not built (candidate next steps). Batch
  verification, the low-confidence "needs review" state, the conversational agent,
  and the RAG layer — originally deferred — are now implemented.
- **OCR is CPU-bound, so the host's CPU sets the latency.** On a normal CPU the
  full verify is ~200 ms (well under the 5 s budget). Tesseract is tuned for
  constrained hosts (`--psm 6`, single OpenMP thread). Note that a heavily
  throttled instance (e.g. Render's free 0.1-CPU tier) can push a single OCR
  call to ~20 s — use at least ~0.5–1 CPU (Render Starter/Standard or equivalent)
  to keep verifications under 5 s.

---

## License

[MIT](LICENSE) © 2026 Jayce Parabellum
