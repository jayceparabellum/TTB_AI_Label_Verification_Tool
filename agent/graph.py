"""The ReAct graph: START -> agent -> (tools | END) -> agent loop.

Phase A is the skeleton — read tools flow straight through ToolNode. The
human-gated confirm_gate for write tools is added in U4; this structure leaves the
seam for it (the conditional edge out of `agent`).
"""

from __future__ import annotations

from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

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


def build_graph(llm=None, checkpointer=None, tools=ALL_TOOLS):
    """Build and compile the agent graph. Pass `llm` to inject a stub in tests; in
    production it defaults to the local Ollama model. `checkpointer` enables memory
    and (later) interrupt/resume."""
    llm = llm if llm is not None else make_llm(tools)
    g = StateGraph(AgentState)
    g.add_node("agent", _agent_node(llm))
    g.add_node("tools", ToolNode(tools))
    g.add_edge(START, "agent")
    # tools_condition routes to "tools" when the last AI message has tool calls,
    # else to END. (U4 will interpose confirm_gate before write tools.)
    g.add_conditional_edges("agent", tools_condition)
    g.add_edge("tools", "agent")
    return g.compile(checkpointer=checkpointer)
