---
last_updated: 2026-06-19
---

# Strategy: TTB AI Label Verification Tool

## Target problem
TTB compliance agents (~47, ~150,000 COLA applications/year) spend roughly half their
day manually confirming a label's artwork matches its application — brand name, alcohol
content, and the mandatory 27 CFR §16.21 government warning. It's rote, slow, inconsistent
eyeball work; a prior vendor tool was abandoned for being too slow (30–40s) and clunky.
The unmet need: do the rote match so fast and so clearly that an agent trusts the verdict
over their own eyes.

## Our approach
A **deterministic verification core owns every PASS/FLAG verdict — never an LLM** — so
verdicts are fast (<5s, usually <1s), reproducible, offline, and auditable. Three
deliberately separated, additive layers:

1. **Verify (core):** OCR + field matching — fuzzy/tolerant brand, numeric proof-aware
   ABV, strict §16.21 warning. The single source of truth for every verdict.
2. **Assistant (agent):** a conversational layer that *orchestrates and explains*
   verdicts and ingests labels in-chat — it never adjudicates pass/fail.
3. **Knowledge (RAG):** cite-or-refuse retrieval over a citation-tagged 27 CFR corpus —
   grounds explanations, never recites from memory, refuses when unsupported.

Load-bearing invariants: the LLM never decides pass/fail; every write is human-gated and
audited; offline by default; nothing persisted (no PII at rest); the button UI stays
primary. The guiding bet is **speed + trust + usability** — and never confidently wrong.

## Who it's for
TTB/COLA **compliance reviewers** (~47), full tech-comfort spectrum. The binding design
constraint is the *least* tech-comfortable agent — large targets, plain language, an
obvious primary button UI. Daily core workflow. (POC: single-user, no roles.)

## Key metrics
- **Margin of error** (confident-wrong ÷ confident verdicts): **< 1%** — headline trust metric.
- **False negatives** (non-compliant confidently PASSed): **0** — worst, regulatory-miss error.
- **False-positive rate** (compliant confidently FLAGged): → 0; ambiguous reads defer to NEEDS REVIEW.
- **Per-verify latency:** **< 5 s** budget (typically < 1 s).
- **RAG quality:** hit / faithfulness / citation (golden set) → 80% / 100% / 100%.
- **Agent-behavior gate:** record→replay invariants (verdict-verbatim, tool routing, confirm-gate, cite-or-refuse) all hold.
- Where they live: `eval/run_eval.py`, `eval/run_rag_eval.py`, `eval/run_agent_eval.py`.

## Tracks
- **Verification accuracy & trust** — deterministic core, image preprocessing, per-flag reasons.
- **Ingestion surface** — single image, pasted text, CSV batch, ZIP/folder, in-chat omni-ingest.
- **Assistant + regulatory knowledge** — the LangGraph agent and cite-or-refuse 27 CFR RAG.
- **Evaluation & quality systems** — the core/RAG/agent eval harnesses that gate accuracy and catch regressions.
- **Deploy & hardening** — offline-capable deploy, security (CVEs, headers, upload caps), error handling.

## Not working on (now)
- COLA / government-system integration; multi-user roles or auth; persisting uploads or PII.
- The LLM/RAG ever deciding pass/fail or auto-approving a change.
- Async / large-batch (>25) processing; PDF/HEIC ingestion; non-English labels.
