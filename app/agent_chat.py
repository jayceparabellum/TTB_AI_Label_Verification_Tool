"""Web glue for the chat agent: build the graph (with a SqliteSaver checkpointer),
stream a turn as SSE, and resume a paused run after human approval.

Kept out of main.py so the streaming generators are easy to test (monkeypatch
`make_llm`). The checkpointer is what makes both session memory and the confirm
gate's interrupt/resume work across stateless HTTP requests; the thread_id keys it.
"""

from __future__ import annotations

import json
import logging
import sqlite3

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agent import config
from agent.graph import build_graph
from agent.images import STORE
from agent.llm import make_llm

_log = logging.getLogger("ttb.agent_chat")

# Seed bundled samples so prompt chips / the demo can verify without an upload.
STORE.seed_samples()
config.ensure_data_dir()
# One long-lived connection -> one checkpointer for the process (POC, local file).
_SAVER = SqliteSaver(sqlite3.connect(config.CHECKPOINT_DB, check_same_thread=False))

_OFFLINE_MSG = ("The assistant is offline right now — the button verifier on the "
               "home page still works for every label.")


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _short(content) -> str:
    try:
        data = content if isinstance(content, dict) else json.loads(content)
    except (TypeError, ValueError):
        return str(content)[:120]
    if "error" in data:
        return data["error"]
    if "overall_pass" in data:
        verdict = "PASS" if data.get("overall_pass") else (
            "NEEDS REVIEW" if data.get("needs_review") else "FLAG")
        return f"{verdict} ({data.get('confidence', '?')}% confidence)"
    if data.get("ok") and data.get("new_status"):
        return f"override recorded → {data['new_status']} (audit #{data.get('recorded_id')})"
    if "total" in data and "passed" in data:          # batch_verify summary
        return (f"{data['total']} total · {data.get('passed', 0)} pass · "
                f"{data.get('flagged', 0)} flag")
    if "downloads" in data and "count" in data:        # export_audit_log
        return f"{data['count']} audit row(s) exported — see downloads below"
    return str(data)[:120]


def _download(content) -> dict | None:
    """A results-CSV download descriptor for the client, if the tool emitted one."""
    try:
        data = content if isinstance(content, dict) else json.loads(content)
    except (TypeError, ValueError):
        return None
    b64 = data.get("results_csv_b64") if isinstance(data, dict) else None
    return {"filename": "batch_results.csv", "b64": b64} if b64 else None


def _downloads(content) -> list[dict] | None:
    """A LIST of download descriptors, if the tool emitted multiple files (e.g. the
    audit export's CSV + XLSX). Distinct from _download(): that surfaces the single
    batch results CSV via `results_csv_b64`; this surfaces a tool's `downloads` list
    so several buttons render in one chat turn. Returns None when absent."""
    try:
        data = content if isinstance(content, dict) else json.loads(content)
    except (TypeError, ValueError):
        return None
    dls = data.get("downloads") if isinstance(data, dict) else None
    if not isinstance(dls, list):
        return None
    out = [d for d in dls if isinstance(d, dict) and d.get("b64")]
    return out or None


def _events(update: dict):
    """Translate one graph stream update into SSE event strings."""
    if "__interrupt__" in update:
        intr = update["__interrupt__"][0]
        val = getattr(intr, "value", {}) or {}
        payload = val if isinstance(val, dict) else {"summary": str(val)}
        yield _sse({"type": "confirm", **payload})
        return
    for _node, payload in update.items():
        if not isinstance(payload, dict):
            continue
        for m in payload.get("messages", []):
            if isinstance(m, ToolMessage):
                evt = {"type": "tool_step", "tool": m.name, "result": _short(m.content)}
                dl = _download(m.content)
                if dl:
                    evt["download"] = dl
                dls = _downloads(m.content)
                if dls:
                    evt["downloads"] = dls
                yield _sse(evt)
            elif isinstance(m, AIMessage):
                for tc in (m.tool_calls or []):
                    yield _sse({"type": "tool_call", "tool": tc["name"]})
                if m.content:
                    yield _sse({"type": "message", "text": m.content})


def _run(graph_input, thread_id: str):
    cfg = {"configurable": {"thread_id": thread_id}}
    try:
        for update in build_graph(llm=make_llm(), checkpointer=_SAVER).stream(
                graph_input, cfg, stream_mode="updates"):
            yield from _events(update)
        yield _sse({"type": "done"})
    except Exception:  # noqa: BLE001 — model/connection failures degrade gracefully
        # Log the real cause (e.g. Ollama unreachable, bad API key, model error) so
        # it's diagnosable in host logs instead of silently masked as "offline".
        _log.exception("agent run failed (backend=%s); degrading to offline message",
                       config.LLM_BACKEND)
        yield _sse({"type": "error", "text": _OFFLINE_MSG})
        yield _sse({"type": "done"})


def stream_chat(message: str, image_id: str | None, thread_id: str):
    """One new agent turn. Pauses (emits a 'confirm' event) before any write."""
    yield from _run({
        "messages": [HumanMessage(message)],
        "active_image_id": image_id,
        "expected": None,
        "last_result_id": None,
        "thread_id": thread_id,
    }, thread_id)


def resume_chat(thread_id: str, decision: str):
    """Resume a paused run after the human approved or cancelled the write."""
    yield from _run(Command(resume=decision), thread_id)
