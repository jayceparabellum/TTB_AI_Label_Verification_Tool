"""The ReAct graph: START -> agent -> (tools | END) -> agent loop.

Phase A is the skeleton — read tools flow straight through ToolNode. The
human-gated confirm_gate for write tools is added in U4; this structure leaves the
seam for it (the conditional edge out of `agent`).
"""

from __future__ import annotations

from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from .confirm import confirm_gate
from .llm import SYSTEM_PROMPT, make_llm
from .state import AgentState
from .tools import ALL_TOOLS


def _agent_node(llm):
    def node(state: AgentState) -> dict:
        msgs = state["messages"]
        # Prepend the system prompt once per run if not already present.
        if not msgs or getattr(msgs[0], "type", None) != "system":
            msgs = [SystemMessage(content=SYSTEM_PROMPT), *msgs]
        return {"messages": [llm.invoke(msgs)]}

    return node


def _route_after_agent(state: AgentState):
    """To the confirm gate when there are tool calls, else end the turn."""
    last = state["messages"][-1]
    return "confirm_gate" if getattr(last, "tool_calls", None) else END


def build_graph(llm=None, checkpointer=None, tools=ALL_TOOLS):
    """Build and compile the agent graph: agent -> confirm_gate -> tools|agent loop.

    Pass `llm` to inject a stub in tests; production defaults to local Ollama.
    `checkpointer` enables memory + interrupt/resume (required for the confirm
    gate's interrupt() to pause and resume across requests)."""
    llm = llm if llm is not None else make_llm(tools)
    g = StateGraph(AgentState)
    g.add_node("agent", _agent_node(llm))
    g.add_node("confirm_gate", confirm_gate)      # routes via Command(goto=...)
    g.add_node("tools", ToolNode(tools))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", _route_after_agent,
                            {"confirm_gate": "confirm_gate", END: END})
    g.add_edge("tools", "agent")
    return g.compile(checkpointer=checkpointer)
