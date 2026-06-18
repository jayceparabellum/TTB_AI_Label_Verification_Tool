"""Web glue for the chat agent: build the graph and stream a turn as SSE.

Kept out of main.py so the streaming generator is easy to test (monkeypatch
`make_llm`) and so the agent layer stays additive to the button UI. The graph is
built per request (cheap — no network until the model is invoked), which keeps the
model swappable for tests and avoids stale caches.
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.graph import build_graph
from agent.images import STORE
from agent.llm import make_llm

# Seed bundled samples so prompt chips / the demo can verify without an upload.
STORE.seed_samples()

_OFFLINE_MSG = ("The assistant is offline right now — the button verifier on the "
               "home page still works for every label.")


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _short(content) -> str:
    """One-line summary of a tool result for the visible tool-step trail."""
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
    return str(data)[:120]


def stream_chat(message: str, image_id: str | None = None):
    """Yield SSE events for one agent turn: tool calls, tool results, model text.

    Read-only Phase-A skeleton — the verdict is carried by tool_step events
    (deterministic), the model only narrates."""
    graph = build_graph(llm=make_llm())
    state = {
        "messages": [HumanMessage(message)],
        "active_image_id": image_id,
        "expected": None,
        "last_result_id": None,
    }
    try:
        for update in graph.stream(state, stream_mode="updates"):
            for _node, payload in update.items():
                for m in payload.get("messages", []):
                    if isinstance(m, ToolMessage):
                        yield _sse({"type": "tool_step", "tool": m.name,
                                    "result": _short(m.content)})
                    elif isinstance(m, AIMessage):
                        for tc in (m.tool_calls or []):
                            yield _sse({"type": "tool_call", "tool": tc["name"]})
                        if m.content:
                            yield _sse({"type": "message", "text": m.content})
        yield _sse({"type": "done"})
    except Exception:  # noqa: BLE001 — model/connection failures degrade gracefully
        yield _sse({"type": "error", "text": _OFFLINE_MSG})
        yield _sse({"type": "done"})
