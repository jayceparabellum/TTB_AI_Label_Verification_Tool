"""Human-in-the-loop confirm gate.

Sits between the agent and the tools. Read-only tool calls flow straight through.
Before any WRITE tool runs, the gate calls interrupt() — pausing the graph at its
checkpoint — and resumes only on an explicit human 'approve'. On 'cancel', the
write never executes; the tool calls are answered with a cancellation message so
the conversation stays consistent, and control returns to the agent to explain.
"""

from __future__ import annotations

from langchain_core.messages import ToolMessage
from langgraph.types import Command, interrupt

from .tools import WRITE_TOOL_NAMES


def _summary(call: dict) -> str:
    a = call.get("args", {})
    if call["name"] == "override_result":
        return (f"Override result {a.get('result_id') or '(current)'} to "
                f"{a.get('new_status', '?')} — reason: {a.get('reason') or '(none given)'}")
    return f"{call['name']}({a})"


def confirm_gate(state: dict):
    """Route the pending tool calls: pass reads through; pause writes for approval."""
    last = state["messages"][-1]
    calls = getattr(last, "tool_calls", None) or []
    write_calls = [c for c in calls if c["name"] in WRITE_TOOL_NAMES]

    if not write_calls:
        return Command(goto="tools")          # read-only: no confirmation needed

    decision = interrupt({
        "type": "confirm",
        "action": write_calls[0]["name"],
        "args": write_calls[0]["args"],
        "summary": _summary(write_calls[0]),
    })

    if str(decision).strip().lower().startswith("approve"):
        return Command(goto="tools")          # human approved -> execute the write

    # Cancelled: answer every pending tool call so the message log stays valid,
    # then hand back to the agent to narrate that nothing changed.
    cancels = [
        ToolMessage(content="Cancelled by the user — no change was made.",
                    tool_call_id=c["id"], name=c["name"])
        for c in calls
    ]
    return Command(goto="agent", update={"messages": cancels})
