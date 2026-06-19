---
title: "feat: Agent Behavior Eval — record(live) → replay(gate) harness"
status: active
date: 2026-06-19
depth: deep
type: feat
origin: docs/prds/0002-agent-behavior-eval.md
---

# feat: Agent Behavior Eval — record(live) → replay(gate)

## Summary

A `record`(live) → `replay`(gate) evaluation harness for the agent layer
(conversational agent + RAG): `record` drives the agent live against a fixed case
set and writes JSON snapshots of each run's transcript + record-time LLM-judge
scores; `gate` replays those snapshots and grades the load-bearing **invariants
deterministically** (no LLM credits), failing on any violation. It is both a
pre-merge gate and the measurement backbone for later iteration. (origin: docs/prds/0002-agent-behavior-eval.md)

## Problem Frame

The deterministic core (`eval/run_eval.py`) and RAG (`eval/run_rag_eval.py`) have
evals; the **agent layer on top has none**. Nothing checks that the agent reports
the deterministic tool's verdict **verbatim** (never its own pass/fail), routes to
the right tool, never auto-approves a WRITE (the confirm gate fires), or that RAG
**cites-or-refuses**. A regression in `agent/` or the prompts (e.g. the LLM narrating
a softened/invented verdict, or skipping the confirm gate) would ship undetected,
and there is no measurement backbone to iterate against. The agent's LLM is
non-deterministic, so the eval must isolate that: record live once, grade by replay.

## Requirements

Traces to PRD 0002 success criteria:
- **R1** `record` runs the agent live (cloud Claude) over the case set and writes a
  snapshot per case (transcript: tool calls, tool results/verdicts, messages,
  confirm-gate interrupts) with record-time judge scores baked in.
- **R2** `gate` replays snapshots and grades deterministically, spending no LLM
  credits: PASS when invariants hold, FAIL on any violation.
- **R3** Invariants enforced: verdict-verbatim (agent's reported verdict matches the
  core `run_verify`/`run_batch`/`reverify_text` result, never the agent's own),
  correct tool routing, confirm-gate fires before any WRITE tool, RAG cite-or-refuse.
- **R4** A demonstrable failing case: a tampered/regressed snapshot makes the gate fail.
- **R5** ≥1 case per invariant and per core flow (`verify_label`, `verify_text`,
  `batch_verify`, `regulatory_lookup`/`explain_flag`).
- **R6** Judge scaffold: ≥1 explanation scored by the LLM-judge at record time, score
  stored and threshold-checked at gate.
- **R7** A report (à la `eval/REPORT.md`) summarizing invariant pass/fail + judge scores.
- **R8** The eval observes only — no change to any agent behavior.

---

## Key Technical Decisions

- **D1 — Record against cloud Claude** (`LLM_BACKEND=anthropic`, `claude-haiku-4-5`).
  Stable tool-routing / instruction-following so snapshots reflect deployed-host
  behavior and invariants hold cleanly. Recording spends credits; the gate is free.
  (Confirmed with user.)
- **D2 — Snapshots are the contract.** `record` is the only live/credit-spending step;
  `gate` is pure replay over committed JSON — deterministic and CI-safe. Mirrors the
  `eval-record` / `eval-gate` skill split.
- **D3 — Judge at record time, scores baked in.** The replay gate only threshold-checks
  stored judge scores; it never calls a model.
- **D4 — Invariants are graded structurally, not by NLP.** verdict-verbatim is checked
  as: (a) a verification tool was actually called, (b) its tool-result equals the core
  ground-truth function on the same inputs, and (c) the agent's final message contains
  the matching verdict keyword (PASS / FLAG / NEEDS REVIEW) and not a contradicting one.
  This is a deterministic proxy for "reported verbatim, not softened/invented."
- **D5 — Separate runner** (`eval/run_agent_eval.py`), not folded into `run_eval.py`.
  The agent eval has a fundamentally different shape (live record + snapshot replay)
  than the stateless core eval; keeping it separate avoids entangling the two.
- **D6 — Drive the existing graph; change no agent code.** The recorder runs
  `agent.graph.build_graph(make_llm(), checkpointer).stream(...)` and captures updates;
  it seeds per-case session state (active_image_id, thread_id, staged batch) and, for
  WRITE cases, resumes with `approve` after capturing the interrupt. (R8)

---

## High-Level Technical Design

```mermaid
flowchart TD
    subgraph record["record (live, cloud Claude — spends credits)"]
      C[agent_cases.py roster] --> R[run_agent_eval record]
      R -->|build_graph().stream, seeded state| G[agent graph + tools]
      G -->|tool_calls · tool_results · messages · interrupt| R
      R -->|score explanations| J[LLM-judge rubric]
      R --> S[(agent_snapshots/*.json<br/>transcript + ground-truth + judge scores)]
    end
    subgraph gate["gate (replay, no LLM — CI-safe)"]
      S --> GR[invariant grader]
      GR -->|verdict-verbatim · routing · confirm-gate · cite-or-refuse| V{all hold?}
      V -->|yes| P[PASS + report]
      V -->|no| F[FAIL + report, non-zero exit]
      S --> TH[judge-score thresholds] --> V
    end
```

Only the **grader/gate** path is exercised in CI; **record** is a manual,
credit-spending refresh. Everything the gate needs lives in the committed snapshot.

---

## Scope Boundaries

### In scope (first cut)
- Snapshot schema + a starter case roster covering each invariant and core flow.
- `record` mode (live, cloud Claude) producing snapshots + record-time judge scores.
- `gate` (replay) mode: deterministic invariant grader + judge-score thresholds + report.
- LLM-judge wired with a small starter rubric.

### Deferred to Follow-Up Work
- The optimization/iteration loop that consumes this backbone (`ce-optimize`-style).
- A full, calibrated judge rubric and broad case coverage.
- CI pipeline wiring beyond a single runnable gate command.
- Per-backend (Ollama vs Claude) comparative snapshots.

### Out of scope
- Replacing `run_eval.py` (core) or `run_rag_eval.py` (RAG) — this layers on top.
- Any change to agent behavior, prompts, or tools (the eval observes only).

---

## Implementation Units

### U1. Snapshot schema + case roster
**Goal:** A typed `AgentEvalCase` roster and a JSON snapshot schema that captures a
run's transcript, the deterministic ground truth to grade against, and judge scores.
**Requirements:** R5, R1 (schema half).
**Dependencies:** none.
**Files:** `eval/agent_cases.py` (create), `eval/agent_snapshots/` (dir, with a
`.gitkeep` or README), `tests/test_agent_eval_cases.py` (create).
**Approach:** `AgentEvalCase` = id, the user message(s), session context (active
sample image id, staged batch, thread id), the expected tool name, the expected
invariant set, and (for verification cases) the inputs needed to compute core ground
truth (brand/abv/sample). Roster covers: `verify_label` (image, PASS + FLAG),
`verify_text`, `batch_verify` (WRITE → confirm gate), `regulatory_lookup` (in-corpus
→ answered+cite), `explain_flag` (→ 16.22 cite), and an out-of-corpus → refused case.
Define the snapshot dataclass/dict shape: `{case_id, inputs, transcript:[{kind, ...}],
ground_truth, judge}` and a `load`/`dump` round-trip.
**Patterns to follow:** `eval/cases.py` (`EvalCase` dataclass + roster), `app/samples.py`.
**Test scenarios:**
- Roster loads; every case names a tool in `agent.tools.ALL_TOOLS` and a non-empty invariant set.
- Snapshot dump→load round-trips a representative transcript without loss.
- Every core flow + invariant from R5/R3 is represented by ≥1 case (assert coverage).
**Verification:** `tests/test_agent_eval_cases.py` green; roster enumerates the required flows.

### U2. Live recorder (`record` mode)
**Goal:** Drive the agent live (cloud Claude), capture each case's transcript +
interrupts, and write a snapshot. No agent-code changes.
**Requirements:** R1, R8, D6.
**Dependencies:** U1.
**Files:** `eval/run_agent_eval.py` (create — `record` entry), `tests/test_agent_eval_recorder.py` (create).
**Approach:** For each case, build the graph with `make_llm()` + a SqliteSaver, seed
state (mirror `app/agent_chat.stream_chat`'s input dict + per-case context), `stream`
updates and capture each AIMessage's `tool_calls`, each `ToolMessage` (name + content),
assistant message text, and `__interrupt__` payloads. For WRITE cases, record that the
interrupt fired, then resume with `Command(resume="approve")` and capture the rest.
Compute and store the **ground truth** (`run_verify`/`reverify_text`/`run_batch` on the
case inputs). Write `eval/agent_snapshots/<case_id>.json`. Real recording needs
`LLM_BACKEND=anthropic` + a key; guard/skip live runs in tests.
**Execution note:** Recorder *mechanics* are unit-tested with a fake LLM (the `_Call`
stub in `tests/test_agent_slice_d.py`) — deterministic, offline. Live recording against
Claude is a manual step, not a unit test.
**Patterns to follow:** `tests/test_agent_slice_d.py` `_Call` stub + `build_graph().stream`;
`app/agent_chat.py` `_events`/`stream_chat`/`resume_chat`; `agent/tools.run_verify`.
**Test scenarios:**
- With a fake LLM that emits a `verify_label` tool call, recording a verify case yields
  a snapshot whose transcript has the tool_call + tool_result and a ground_truth equal
  to `run_verify` on the same inputs.
- A WRITE case (fake LLM emits `batch_verify`) records an interrupt step before the tool
  result, and the post-`approve` resume is captured.
- Recorder writes valid JSON that U1's loader round-trips.
- No agent module is mutated (recorder imports and drives only).
**Verification:** Fake-LLM recordings produce schema-valid snapshots; a documented
`record` command produces real snapshots when `LLM_BACKEND=anthropic`.

### U3. Invariant grader + `gate` (replay) mode
**Goal:** Replay snapshots and grade the four invariants deterministically; no LLM.
**Requirements:** R2, R3, R4.
**Dependencies:** U1 (schema). Independent of U2 (graded against hand-written snapshots).
**Files:** `eval/run_agent_eval.py` (`gate` entry + grader), `tests/test_agent_eval_gate.py` (create).
**Approach:** For each snapshot: **verdict-verbatim** (a verification tool was called;
its tool-result equals `ground_truth`; the final message contains the matching verdict
keyword and no contradicting one — D4); **tool routing** (expected tool present in
transcript tool_calls); **confirm-gate** (WRITE cases have an interrupt step before the
tool executed); **cite-or-refuse** (RAG tool results are `answered`+citation or
`refused`+no-citation). Aggregate pass/fail; non-zero exit on any failure.
**Execution note:** Characterization-first — write hand-crafted PASS and each-invariant-
FAIL snapshots as fixtures before the grader, so each invariant has a red case.
**Patterns to follow:** `eval/run_eval.py` `_score`; `agent/tools.run_verify` (ground truth).
**Test scenarios:**
- A clean snapshot (correct tool, verdict matches ground truth, message keyword matches,
  RAG cited) → PASS.
- verdict-verbatim FAIL: message says PASS but ground_truth/tool-result is FLAG → fail.
- routing FAIL: expected `verify_text` but transcript called `verify_label` → fail.
- confirm-gate FAIL: a WRITE snapshot with no interrupt before the tool result → fail.
- cite-or-refuse FAIL: a `regulatory_lookup` result that answered with no citation → fail.
- Gate over the whole snapshot dir exits non-zero iff any case fails (R4).
**Verification:** All five FAIL fixtures fail their specific invariant; the clean
fixture passes; whole-dir gate exit code correct.

### U4. LLM-judge (record-time) + threshold check
**Goal:** Score explanation quality at record time with a starter rubric; store scores
in the snapshot; threshold-check them at gate.
**Requirements:** R6, D3.
**Dependencies:** U2 (record), U3 (gate).
**Files:** `eval/agent_judge.py` (create — rubric + judge call via `agent.llm`),
`eval/run_agent_eval.py` (call judge in record; threshold in gate),
`tests/test_agent_eval_judge.py` (create).
**Approach:** A small rubric (e.g. faithfulness-to-verdict + plain-language clarity,
scored 1–5 with a one-line justification) judged by the configured model
(`agent.llm.make_llm` / cloud Claude) at record time; store `{score, justification}`
in the snapshot's `judge` block. Gate checks `score >= threshold` (configurable, default
documented). Judge calls are mocked in unit tests.
**Patterns to follow:** `agent/llm.py` model factory; `rag/generate.py` LLM-call shape.
**Test scenarios:**
- With a mocked judge returning a fixed score, record bakes `{score, justification}` into the snapshot.
- Gate passes when stored score ≥ threshold, fails when below.
- Gate performs no model call (judge is record-time only) — assert no LLM is constructed in gate.
**Verification:** Snapshot carries a judge block; gate threshold check passes/fails correctly with no LLM call.

### U5. Report + runner entrypoint + docs
**Goal:** A single `record`/`gate` CLI, a markdown report, and README/eval docs.
**Requirements:** R7.
**Dependencies:** U3, U4.
**Files:** `eval/run_agent_eval.py` (argparse `record`/`gate` subcommands + report writer),
`eval/AGENT_REPORT.md` (generated), `README.md` (document the agent eval),
`tests/test_agent_eval_report.py` (create).
**Approach:** `python eval/run_agent_eval.py gate` (default) replays + writes
`eval/AGENT_REPORT.md` (per-case invariant table + judge scores + summary) and exits
non-zero on failure; `... record` refreshes snapshots (needs `LLM_BACKEND=anthropic`).
Document the record→gate workflow + the credit cost of recording.
**Patterns to follow:** `eval/run_eval.py` report writing + `eval/REPORT.md`.
**Test scenarios:**
- Report renders a row per case with per-invariant pass/fail and judge score.
- `gate` over a passing snapshot dir exits 0 and writes the report; a failing dir exits non-zero.
- README documents `record` (live, credits) vs `gate` (free, CI) and `LLM_BACKEND=anthropic`.
**Verification:** Report generated; exit codes correct; README explains the workflow.

---

## Risks & Mitigations

- **Snapshot staleness** — agent/prompt changes silently invalidate snapshots, so the
  gate grades stale behavior. Mitigation: document a re-record trigger (any `agent/`
  change); a follow-up could hash the prompt/tool set into snapshots and warn on drift.
- **verdict-verbatim proxy is imperfect** — keyword matching could miss a cleverly
  softened verdict. Mitigation: D4 also requires the tool-result==ground-truth and a
  real tool call, so the agent can't fabricate; keyword check guards the narration.
  The LLM-judge (faithfulness) backstops the softer cases.
- **Recording cost / flakiness** — live Claude recording spends credits and can vary.
  Mitigation: record is manual + infrequent; the gate (the CI path) is free and stable.
- **Eval accidentally alters agent behavior** — Mitigation: recorder only imports and
  drives `build_graph`; a test asserts no agent module is modified (R8).

## Verification Strategy

- Per-unit tests above; the **gate + grader (U3) and judge threshold (U4) are fully
  offline** (synthetic/mocked), so CI runs them with no credits.
- The recorder (U2) is unit-tested with the fake-LLM `_Call` stub; real recording is a
  documented manual step.
- End-to-end manual: `LLM_BACKEND=anthropic python eval/run_agent_eval.py record` →
  commit snapshots → `python eval/run_agent_eval.py gate` passes; then tamper a snapshot
  and confirm the gate fails (R4).

## Sources & Research

- This codebase (worked this session): `agent/graph.py` (`build_graph`), `agent/tools.py`
  (`ALL_TOOLS`, `READ_TOOLS`/`WRITE_TOOLS`, `run_verify`), `agent/confirm.py`
  (`confirm_gate` interrupt), `agent/llm.py` (`make_llm`, `SYSTEM_PROMPT`),
  `app/agent_chat.py` (`stream_chat`/`resume_chat`/`_events`), `eval/run_eval.py`,
  `eval/run_rag_eval.py`, `tests/test_agent_slice_d.py` (`_Call` fake-LLM + gate pattern),
  `rag/generate.py` (answer/explain_flag shape).
- Skills mirrored: `eval-record` (live snapshot record), `eval-gate` (replay grade).
- Origin: `docs/prds/0002-agent-behavior-eval.md`.
