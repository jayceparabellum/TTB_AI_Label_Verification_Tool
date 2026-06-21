# PRD 0002: Agent Behavior Eval (record → replay)

- **Status:** Implemented (2026-06-19)
- **Author:** jayceparabellum
- **Created:** 2026-06-19

## Summary

An evaluation system for the AI/agent layer (conversational agent + RAG) that scores agent **behavior** — both as a CI/pre-merge **gate** and as the measurement backbone for **iterating** toward the application's intended behavior — using a **record (live) → replay (gate)** split so the gate is deterministic, free, and CI-stable.

## Problem

The deterministic core has an eval (`eval/run_eval.py`) and RAG has one (`eval/run_rag_eval.py`), but the **agent layer that sits on top has none**. Nothing automatically validates the agent's load-bearing invariants — that it reports the deterministic tool's verdict **verbatim** (never its own pass/fail), routes to the right tool, never auto-approves a write (the confirm gate fires), and that RAG **cites-or-refuses**. Today a regression in agent behavior (e.g. the LLM narrating a softened or invented verdict, or skipping the confirm gate) would ship undetected. Whoever changes `agent/` or the prompts has no signal that the product's intent still holds, and no measurement backbone to iterate against.

## Goals / Success Criteria

- **`record` mode** runs the agent **live** over a fixed case set and writes snapshots capturing each run's transcript — tool calls, tool results/verdicts, assistant messages — plus the LLM-judge's quality scores, baked in at record time.
- **`gate` mode** **replays** snapshots and grades them deterministically, **spending no LLM credits**:
  - **PASS** when all invariants hold.
  - **FAIL** on any violation — the agent reports a verdict that doesn't match the deterministic tool result (verbatim check), routes to the wrong tool, a WRITE tool runs without the confirm gate, or a RAG answer lacks a citation.
- A **demonstrable failing case**: introduce a regression (e.g. make the agent narrate a verdict the tool didn't return) and the gate fails loudly.
- At least one case per **invariant** and per **core agent flow** (`verify_label`, `verify_text`, `batch_verify`, `regulatory_lookup`/`explain_flag`).
- **Judge scaffold present**: at least one explanation scored by the LLM-judge at record time, its score stored in the snapshot and threshold-checked at gate time.
- A **report** (à la `eval/REPORT.md`) summarizing invariant pass/fail + judge scores.

## Non-goals

- Replacing the deterministic-core eval (`run_eval.py`) or the RAG eval (`run_rag_eval.py`) — this is the **agent-behavior layer on top of them**.
- An **automated optimization loop** — this PRD delivers the measurement backbone that a loop would run against, not the loop itself (follow-up).
- A **full, calibrated judge rubric** or exhaustive case coverage — v1 ships a small starter rubric; expansion is a fast-follow.
- Running the **judge live at gate time** — the judge runs at record time only.
- CI pipeline wiring (beyond making the gate runnable as a single command).

## Scope

### In scope (the first cut)
- An agent eval **case set** (`eval/agent_cases.py`): each case = user turn(s) + session context (active image / staged batch / thread) + expected tool + expected invariants.
- A **snapshot format** (JSON) and storage (`eval/agent_snapshots/`): transcript + record-time judge scores.
- **`record` mode** — drives the agent live (via the existing `app/agent_chat` / `agent/graph` path), writes snapshots, runs the judge.
- **`gate` (replay) mode** — deterministic invariant assertions + judge-score threshold checks; emits a report; non-zero exit on failure.
- **LLM-judge** wired in with a small starter rubric (explanation clarity / faithfulness).

### Out of scope
- The optimization/iteration loop itself (this is its backbone).
- Full judge rubric + broad case coverage (fast-follow).
- CI integration; replacing existing evals.

## Proposed Design

> Detailed architecture is deferred to a `/ce-plan` pass before implementation (per request). The below is the rough shape.

### New services / components
- `eval/agent_cases.py` — `AgentEvalCase` definitions (inputs, session context, expected tool, expected invariants, judge-rubric ref).
- `eval/run_agent_eval.py` — two entry points: `record` (live → snapshots, mirrors the `eval-record` pattern) and `gate` (replay → grade, mirrors `eval-gate`).
- `eval/agent_snapshots/*.json` — recorded transcripts + baked-in judge scores.
- An **invariant grader** — verdict-verbatim (compare the agent's reported verdict against the core `run_verify`/`run_batch`/`reverify_text` result), tool-routing, confirm-gate-fired-on-write, RAG cite-or-refuse.
- An **LLM-judge** module — scores explanation quality at record time using the configured model factory (`agent/llm.make_llm` / cloud Claude); rubric stored alongside.

### Existing code touched
- `agent/graph.py`, `agent/tools.py`, `agent/llm.py`, `app/agent_chat.py` — driven programmatically to produce transcripts (no behavior changes; the eval observes).
- Reuse `agent/tools.run_verify` / `app.batch.run_batch` / `app.verify.reverify_text` as ground truth for the verdict-verbatim check.
- Mirror conventions from `eval/run_eval.py` (report writing) and the `eval-record` / `eval-gate` skills.

### Data model changes
- None (no DB). New on-disk JSON snapshots under `eval/agent_snapshots/`.

### External dependencies
- None new — the judge uses the already-present `langchain-anthropic` (cloud Claude) or local Ollama via the existing model factory.

## Open questions

- Which backend records the **canonical** snapshots — local Ollama (`llama3.2:3b`) or cloud Claude (`LLM_BACKEND=anthropic`)? Behavior differs; the gate should grade snapshots from a fixed, declared backend.
- Judge **model + rubric** specifics, and how the judge is calibrated / its threshold chosen.
- Exact **invariant set** and the first **case roster** size.
- Should agent-eval be a **separate runner** or unified with `run_eval.py` / `run_rag_eval.py` under one entry point?
- How (and whether) the gate wires into **CI** — is there a CI pipeline today?
- How snapshots stay **fresh** — re-record cadence / detecting when agent or prompt changes invalidate them.

## References

- Existing evals: `eval/run_eval.py` (deterministic core), `eval/run_rag_eval.py` (RAG hit-rate / faithfulness / citation).
- Skills mirrored: `eval-record` (record live snapshots), `eval-gate` (replay grade), `ce-optimize` (the future iteration loop this feeds).
- Agent layer: `agent/graph.py`, `agent/tools.py`, `agent/confirm.py`, `agent/llm.py`, `app/agent_chat.py`.
- Prior PRD: `docs/prds/0001-audit-log-export.md`.
