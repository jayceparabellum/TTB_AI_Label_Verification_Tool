"""Layer 2 — conversational LangGraph agent over the deterministic verification core.

The agent ORCHESTRATES and EXPLAINS; it never adjudicates. Every pass/fail comes
from the deterministic core (app/), wrapped by read tools; write tools are
human-gated. Nothing here touches the network except the local Ollama endpoint.
"""
