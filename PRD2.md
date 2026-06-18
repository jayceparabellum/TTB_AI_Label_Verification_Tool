# PRD v2: TTB AI Label Verification Tool — Full-System PRD (3 layers)

- **Status:** Adopted (documents the shipped system, as of this date)
- **Author:** jayceparabellum
- **Created:** 2026-06-18
- **Supersedes:** [PRD-v1.md](PRD-v1.md)
- **Live:** https://ttb-label-verification-9q01.onrender.com

## Summary

A fully-offline tool that reads an alcohol-beverage label image and returns a clear **PASS / FLAG** for each compliance check (brand name, alcohol content, mandatory government warning), with two additive layers on top: a conversational agent that drives every action in plain language and a citation-grounded RAG layer that answers 27 CFR questions — where the **LLM and RAG only orchestrate and explain; deterministic code owns every pass/fail and a human commits every decision.**

## Problem

TTB compliance reviewers manually compare a submitted label against the claimed COLA application data and the federal labeling rules. This is slow, and — in a federal-audit setting — a *confidently wrong* call is a real liability. The work happens on a locked-down network where nothing may be sent to a cloud service. Reviewers range to the least tech-comfortable users (the 73-year-old benchmark user), so the tool must be obvious and forgiving. The pain is felt by the reviewer (throughput, fear of error) and by the agency (audit risk, no defensible trail of who decided what and why).

## Goals / Success Criteria

Observable signals, all currently met by the shipped system:

- **Decision correctness:** on the 16-case evaluation board (3 clean + 10 degraded + 3 varied product labels), **16/16 correct, 0.00% margin of error** (target < 1%). Every case is a confident verdict or a safe deferral; the only defined failure is a *confident wrong* verdict, of which there are zero.
- **Latency:** every verify path completes in **< 5 s including cold start** (observed max ~290 ms server compute locally; ~1 s round-trip on the free Render instance).
- **Regulatory grounding:** RAG eval **hit-rate 100%, faithfulness 100%, citation 100%** across 14 golden Q&A cases; out-of-corpus questions are refused, not answered.
- **Offline:** a network-cut test (outbound sockets blocked) proves verify + RAG run with **zero egress**.
- **Auditability:** every write (override, manual entry, batch) is recorded append-only with who/what/when/why; the agent can never auto-approve.
- **Test health:** **154 automated tests pass**; the suite is hermetic (deterministic BM25-only regime regardless of host install state).

## Non-goals

Explicitly **not** success for this system:

- The LLM or RAG **deciding pass/fail**, or the agent **auto-submitting a final compliance approval**. (Hard guardrail.)
- Integration with **COLA or any TTB/government system**; this is a standalone POC.
- Storing **real PII**, adding **auth**, or persisting submissions; verify is stateless (only the audit log + chat checkpoints persist locally).
- **Cloud LLMs or any outbound call** at runtime.
- **Replacing the button UI** with chat; chat is additive.
- **Bold-detection** of the warning typography (ALL-CAPS header is checked; bold is documented as out of scope).

## Invariants (non-negotiable)

1. LLM orchestrates and explains, **never adjudicates**; the deterministic core owns every pass/fail; RAG grounds explanations but gets **no vote**.
2. A verification result is returned in **< 5 s including cold start**; RAG and chat stay **off** the 5 s hot path.
3. **Fully offline/local**; nothing leaves the network at runtime.
4. **Two matching strategies kept separate**: fuzzy brand + ABV (tolerant of formatting) vs. strict, word-for-word 27 CFR §16.21 warning with an ALL-CAPS `GOVERNMENT WARNING:` header.
5. Every write/override is **human-gated** via the confirm node and **audit-logged**; the agent can never autonomously submit a final approval.
6. All regulatory output is **citation-required** and **refuses** ("Not found in the regulations on file.") when retrieval is empty or low-confidence.
7. The **button UI is primary and always available**; chat is additive and degrades gracefully when the model is absent.

## Scope

### In scope (shipped)

- **Layer 1 — Deterministic verifier:** single-label verify (image upload or one of three bundled samples), text re-verify, and **batch verify** (CSV mapping + a folder of labels → results table → filter to flagged → CSV export), all within the < 5 s budget; per-label timing tracked.
- **Layer 2 — Conversational agent:** an SSE chat panel that drives every action in plain language, with visible tool steps and suggested-prompt chips. Read tools flow through; write tools pause at a **human-in-the-loop confirm gate** (Approve/Cancel) and are written to an **append-only audit log**.
- **Layer 3 — Regulatory RAG:** grounded, cite-or-refuse answers over a committed, citation-tagged 27 CFR corpus (Part 16 warning + per-commodity labeling for Parts 4 wine, 5 spirits, 7 malt). Hybrid retrieval: BM25 fused with optional dense BGE-small embeddings via reciprocal-rank fusion.

### Out of scope (this PRD)

- Everything in **Non-goals** above.
- Full structured OCR of all seven label fields (today: brand + ABV + warning are adjudicated; class/type, net contents, producer, country are best-effort raw text, clearly labeled "not adjudicated").
- The TTB Beverage Alcohol Manual (BAM) and Parts other than 4/5/7/16 in the corpus.
- A versioning/diff UI for the corpus or audit log.

## Proposed Design (as built)

### New services / components

- **`app/` (Layer 1):** `ocr.py` (local Tesseract psm-4 + deskew / CLAHE contrast / upscaling + readability gate), `matching.py` (fuzzy brand via rapidfuzz ≥ 95; numeric proof-aware ABV; strict warning via anchored-window fuzzy ≥ 99 + ALL-CAPS header + inconclusive/defer), `verify.py` (orchestrator: `verify_label`, `reverify_text`, `verify_fields`), `reference.py` (pinned official §16.21 text), `batch.py` (`run_batch`, `parse_csv`, `results_to_csv`, cap), `models.py` (`VerificationResult`), `main.py` (FastAPI routes + Jinja templates).
- **`agent/` (Layer 2):** `state.py` (LangGraph `AgentState`), `graph.py` (StateGraph → agent → confirm_gate → tools), `confirm.py` (`interrupt()`-based HITL gate), `tools.py` (10 tools wrapping the core: `verify_label`, `extract_label_fields`, `verify_warning`, `list_flagged`, `regulatory_lookup`, `explain_flag`, `validate_class_type` read; `override_result`, `manual_fallback`, `batch_verify` write), `audit.py` (append-only SQLite, reason mandatory, no update/delete API), `llm.py` (local ChatOllama, swappable), `config.py`, `images.py`. Web: `app/agent_chat.py` (SSE stream + interrupt/resume over stateless HTTP via a thread-keyed `SqliteSaver`), `templates/agent.html`, `static/agent.js`.
- **`rag/` (Layer 3):** `ingest.py` (citation-tagged chunks), `retrieve.py` (BM25 + heading weighting + coverage-first ranking + RRF dense fusion seam), `dense.py` (`BGEEmbedder`, in-memory cosine `DenseIndex`, `RAG_DENSE` switch, offline local-only model load), `generate.py` (extractive cite-or-refuse + query expansion), `corpus/cfr_excerpts.json` (12 verified chunks), `corpus/ecfr_verified.json` (offline snapshot of eCFR-verified section numbers).

### Existing code touched

Layer 1 is unchanged by Layers 2–3 (tools **wrap**, never reimplement it). `app/main.py` gained the `/chat`, `/agent/chat`, `/agent/resume` routes and `PROMPT_CHIPS`; `base.html` gained the Chat nav link. The standard `Dockerfile` now also copies `agent/` + `rag/` so chat ships with the deployed image.

### Data model changes

- **Stateless verify:** nothing persisted per request.
- **Local SQLite under `.agent_data/` (gitignored, ephemeral):** chat **checkpoints** (thread-keyed session memory + interrupt/resume) and the **append-only audit log** (`actor`, `action`, `target_result_id`, `old/new_verdict`, `reason`, timestamp).
- **Committed data:** the citation-tagged corpus and the eCFR-verified-sections snapshot.

### External dependencies

FastAPI, uvicorn, Jinja2, pytesseract (+ system Tesseract), rapidfuzz, opencv-python-headless, numpy; langgraph, langgraph-checkpoint-sqlite, langchain-core, langchain-ollama (+ a host **Ollama** runtime/model); rank-bm25. Optional/host-deferred: `sentence-transformers` (enables the dense BGE-small backend), chromadb (deferred persistence). No cloud APIs.

## Evaluation & metrics

- **Decision board (`eval/run_eval.py` → `eval/REPORT.md`):** 16/16 confident, 16/16 correct, **0.00% margin of error**, max latency ~290 ms. Plus a separate out-of-scope stress set (real bottle photos) that all safely defer to human review.
- **RAG eval (`eval/run_rag_eval.py`):** 14 golden cases, **100% / 100% / 100%** hit-rate / faithfulness / citation.
- **Tests:** 154 passing, including button-parity, HITL pause/approve/cancel + audit round-trip, cite-or-refuse, the 7 named label fixtures, a < 5 s latency bound, the offline network-cut proof, dense-fusion (offline stub embedder), and the eCFR-verified-section guard.

## Deployment

- **Standard Docker image** (`Dockerfile`) bundles Tesseract + all three layers; on a lean host the LLM (Ollama) and dense embeddings are simply absent, so **chat degrades gracefully and RAG runs BM25-only** — no crash. Deployed on **Render (free plan)** at the live URL above; health check at `/health`; `autoDeploy: false` (manual deploy).
- **Full agent host image** (`Dockerfile.agent`) additionally bundles Ollama and bakes the 3B model + corpus in at build time for a ~4 GB box that runs the complete chat experience fully offline.

## Known limitations / host-deferred

- **Ollama model** needs a ~4 GB host; the free Render plan can't run it, so chat there shows the graceful offline message and the button verifier is the path.
- **Dense BGE-small** retrieval is optional (`pip install sentence-transformers`, `RAG_DENSE=auto`); default is BM25-only, which is fully offline and deterministic. Chroma persistence is deferred (the corpus is small enough for exact in-memory cosine).
- **Curated corpus, not full live eCFR:** Parts 4/5/7/16 labeling slices; §16.21 is verbatim. Section **numbers were verified against the live eCFR structure API (issue date 2026-06-10)**; chunk **wording is a faithful conservative summary** — confirm exact text against each `source_url` before operational use.
- **Warning typography:** ALL-CAPS header is enforced; **bold** is not detected (documented).
- **Real-world bottle photography** is out of the product's input scope; local Tesseract safely defers rather than guessing.
- **Free-plan cold starts:** the first request after idle is slow (CPU-throttled); not a correctness issue.
- **Ephemeral audit/checkpoint storage** on Render's disk (resets on redeploy).

## Open questions

- Durable, locked-down hosting for the Ollama model so production chat isn't degraded — which host/SLA?
- Automating the full live eCFR ingest (all of Parts 4/5/7/16 + BAM) and its refresh cadence + re-verification.
- Persistent, tamper-evident storage for the audit log if this moves past POC (currently ephemeral SQLite).
- Whether/when COLA or any TTB-system integration becomes in-scope (today a hard non-goal).
- Expanding adjudicated fields beyond brand/ABV/warning (class/type, net contents) and the standards-of-identity coverage that would require.

## References

- [PRD-v1.md](PRD-v1.md) (superseded), [Design.md](Design.md), [PVD.md](PVD.md)
- Implementation plan: [docs/plans/2026-06-18-001-feat-conversational-agent-rag-plan.md](docs/plans/2026-06-18-001-feat-conversational-agent-rag-plan.md)
- Evals: `eval/run_eval.py` → `eval/REPORT.md`; `eval/run_rag_eval.py` + `eval/rag_golden.json`
- Repo: https://github.com/jayceparabellum/TTB_AI_Label_Verification_Tool · Live: https://ttb-label-verification-9q01.onrender.com
