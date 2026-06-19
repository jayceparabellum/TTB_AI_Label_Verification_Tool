"""Live recorder (`record` mode): drive the agent and snapshot each run.

Mirrors `app/agent_chat.stream_chat`/`resume_chat`: it builds the real graph with
`make_llm()` + a SqliteSaver, seeds per-case session state, streams updates, and
translates each into a typed transcript step (tool_call / tool_result / message /
interrupt) — the same shape the gate replays. For WRITE cases it records the
confirm-gate interrupt, then resumes with `Command(resume="approve")` and captures
the rest. It computes the deterministic GROUND TRUTH (`run_verify` /
`reverify_text` via `run_verify_text` / `run_batch`) for the same inputs, scores
explanations with the record-time LLM-judge (U4), and writes a snapshot per case.

It OBSERVES only — it imports and drives `agent.graph.build_graph`; it changes no
agent code (PRD R8). Real recording needs `LLM_BACKEND=anthropic` + a key and
spends credits; the recorder MECHANICS are unit-tested offline with a fake LLM.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agent import tools as T
from agent.graph import build_graph
from agent.images import STAGING, STORE
from agent.llm import make_llm
from eval import agent_cases as AC
from eval.agent_cases import AgentEvalCase, Snapshot


def _seed_state(case: AgentEvalCase) -> dict:
    """The graph input dict for a case — mirrors stream_chat's seed."""
    return {
        "messages": [HumanMessage(case.message)],
        "active_image_id": case.active_image_id,
        "expected": None,
        "last_result_id": None,
        "thread_id": case.thread_id or case.id,
    }


def _record_update(update: dict, transcript: list[dict]) -> bool:
    """Append transcript steps for one graph stream update. Returns True if this
    update was a confirm-gate interrupt (so the caller knows to resume)."""
    if "__interrupt__" in update:
        intr = update["__interrupt__"][0]
        val = getattr(intr, "value", {}) or {}
        val = val if isinstance(val, dict) else {"summary": str(val)}
        transcript.append(AC.interrupt_step(
            action=val.get("action", "") or "", summary=val.get("summary", "") or ""))
        return True
    for _node, payload in update.items():
        if not isinstance(payload, dict):
            continue
        for m in payload.get("messages", []):
            if isinstance(m, ToolMessage):
                transcript.append(AC.tool_result_step(m.name, _content(m.content)))
            elif isinstance(m, AIMessage):
                for tc in (m.tool_calls or []):
                    transcript.append(AC.tool_call_step(tc["name"], tc.get("args", {})))
                if m.content:
                    transcript.append(AC.message_step(m.content))
    return False


def _content(content):
    """A ToolMessage's content is JSON text or already a dict; normalize to a dict."""
    if isinstance(content, dict):
        return content
    import json
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return {"raw": str(content)}


def _ground_truth(case: AgentEvalCase) -> Optional[dict]:
    """The deterministic core result for the case inputs (None for pure-RAG cases)."""
    vi = case.verify_inputs
    if not vi:
        return None
    kind = vi.get("kind")
    if kind == "image":
        return T.run_verify(vi["image_id"], vi["brand"], vi["alcohol_content"])
    if kind == "text":
        return T.run_verify_text(vi["label_text"], vi["brand"], vi["alcohol_content"],
                                 vi.get("expected_warning", ""))
    if kind == "batch":
        images, csv = T._samples_batch()
        from app import batch as _batch
        r = _batch.run_batch(images, csv)
        return {"error": r.error} if r.error else dict(r.summary)
    return None


def record_case(case: AgentEvalCase, llm=None, run_judge: bool = True) -> Snapshot:
    """Drive one case through the graph and return its snapshot. `llm` defaults to
    `make_llm()` (live); pass a stub to record offline."""
    llm = llm if llm is not None else make_llm()
    saver = SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))
    graph = build_graph(llm=llm, checkpointer=saver)
    cfg = {"configurable": {"thread_id": case.thread_id or case.id}}

    transcript: list[dict] = []
    interrupted = False
    for update in graph.stream(_seed_state(case), cfg, stream_mode="updates"):
        if _record_update(update, transcript):
            interrupted = True
    if interrupted:
        for update in graph.stream(Command(resume="approve"), cfg, stream_mode="updates"):
            _record_update(update, transcript)

    snap = Snapshot(
        case_id=case.id, expected_tool=case.expected_tool,
        invariants=sorted(case.invariants), is_write=case.is_write,
        inputs=dict(case.verify_inputs or {}),
        transcript=transcript, ground_truth=_ground_truth(case))
    if run_judge:
        from eval.agent_judge import judge_snapshot
        snap.judge = judge_snapshot(snap)
    return snap


def run_record(snapshot_dir: Path | None = None, only: list[str] | None = None,
               run_judge: bool = True, llm=None) -> int:
    """Record the roster (or a subset) to snapshots. Returns a process exit code.
    Seeds bundled samples so image cases have something to verify."""
    STORE.seed_samples()
    cases = [c for c in AC.ROSTER if not only or c.id in set(only)]
    if not cases:
        print(f"No matching cases for {only!r}.")
        return 1
    written = []
    for case in cases:
        if case.use_staged_batch:
            STAGING.clear(case.thread_id or case.id)
        snap = record_case(case, llm=llm, run_judge=run_judge)
        path = AC.dump(snap, (snapshot_dir / f"{case.id}.json") if snapshot_dir else None)
        written.append(path)
        print(f"recorded {case.id} -> {path}")
    print(f"\nWrote {len(written)} snapshot(s). Commit them, then run the gate.")
    return 0
