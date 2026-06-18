"""Local model factory (Ollama) + the system prompt that encodes the invariants.

The factory is swappable so tests inject a stub (no running Ollama needed) and the
deployed app uses the real local model. The system prompt is the behavioral
guardrail: orchestrate, never adjudicate.
"""

from __future__ import annotations

from . import config
from .tools import ALL_TOOLS

SYSTEM_PROMPT = (
    "You are a verification ASSISTANT for U.S. TTB alcohol-label compliance "
    "agents. You ORCHESTRATE tools and EXPLAIN results in plain language. You do "
    "NOT decide pass/fail yourself.\n"
    "Rules:\n"
    "- Every pass/fail comes from a verification tool. Report EXACTLY what the "
    "tool returned; never soften, invent, or override a verdict.\n"
    "- Never approve or reject a label. Only a human can commit that (via a "
    "human-gated tool).\n"
    "- When OCR cannot read a field, offer the manual-fallback path; do not guess "
    "the value.\n"
    "- For any regulatory question, call the regulatory lookup tool and cite the "
    "rule; never recite regulations from memory.\n"
    "- Explain flags in plain language a non-technical agent can act on."
)


def make_llm(tools=ALL_TOOLS):
    """Build a tool-bound ChatOllama from config. Imported lazily-friendly: the
    model connection is not opened until the model is actually invoked."""
    from langchain_ollama import ChatOllama

    llm = ChatOllama(
        model=config.OLLAMA_MODEL,
        base_url=config.OLLAMA_BASE_URL,
        temperature=config.OLLAMA_TEMPERATURE,
    )
    return llm.bind_tools(tools) if tools else llm
