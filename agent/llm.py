"""Model factory + the system prompt that encodes the invariants.

The factory is swappable so tests inject a stub (no running model needed). It
builds either a LOCAL Ollama model (default, fully offline) or cloud Claude via
Anthropic when LLM_BACKEND=anthropic — the deployed-host path, since a lean cloud
host has no local model. The system prompt is the behavioral guardrail:
orchestrate, never adjudicate; the backend choice does not change that contract.
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
    "- To verify a label IMAGE the user uploaded, call verify_label. To verify "
    "label TEXT the user pasted or typed, call verify_text with that text.\n"
    "- Never approve or reject a label. Only a human can commit that (via a "
    "human-gated tool).\n"
    "- When OCR cannot read a field, offer the manual-fallback path; do not guess "
    "the value.\n"
    "- For any regulatory question, call the regulatory lookup tool and cite the "
    "rule; never recite regulations from memory.\n"
    "- To export, download, or save the audit log / decision history, call "
    "export_audit_log and hand back the files it returns.\n"
    "- To check whether the audit log is intact / untampered / verifiable, call "
    "verify_audit_log and report its verdict verbatim.\n"
    "- Explain flags in plain language a non-technical agent can act on."
)


def _build_model():
    """Construct the chat model for the configured backend. Connections are lazy
    (not opened until the model is invoked), so this is import-safe."""
    if config.LLM_BACKEND == "anthropic":
        from langchain_anthropic import ChatAnthropic
        # Reads ANTHROPIC_API_KEY from the environment (a host secret).
        return ChatAnthropic(
            model=config.ANTHROPIC_MODEL,
            temperature=config.LLM_TEMPERATURE,
            timeout=30,
            max_retries=1,
        )
    from langchain_ollama import ChatOllama
    return ChatOllama(
        model=config.OLLAMA_MODEL,
        base_url=config.OLLAMA_BASE_URL,
        temperature=config.OLLAMA_TEMPERATURE,
    )


def make_llm(tools=ALL_TOOLS):
    """Build a tool-bound chat model from config (Ollama by default, Claude when
    LLM_BACKEND=anthropic). The same tool-calling contract holds for both."""
    llm = _build_model()
    return llm.bind_tools(tools) if tools else llm
