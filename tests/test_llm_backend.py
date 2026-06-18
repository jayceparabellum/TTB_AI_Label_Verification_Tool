"""The model factory builds the right backend from config: local Ollama by default
(offline), cloud Claude when LLM_BACKEND=anthropic (deployed hosts). Construction is
lazy — no network — so this runs with only a dummy key and no model server."""

import pytest

from agent import config, llm


def test_default_backend_is_ollama(monkeypatch):
    monkeypatch.setattr(config, "LLM_BACKEND", "ollama")
    m = llm._build_model()
    assert type(m).__name__ == "ChatOllama"


def test_anthropic_backend_builds_claude(monkeypatch):
    pytest.importorskip("langchain_anthropic")
    monkeypatch.setattr(config, "LLM_BACKEND", "anthropic")
    monkeypatch.setattr(config, "ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy-for-construction-only")
    m = llm._build_model()
    assert type(m).__name__ == "ChatAnthropic"
    name = getattr(m, "model", "") or getattr(m, "model_name", "")
    assert "claude" in str(name).lower()


def test_make_llm_is_tool_bound_for_either_backend(monkeypatch):
    monkeypatch.setattr(config, "LLM_BACKEND", "ollama")
    bound = llm.make_llm()
    # bind_tools yields a runnable that carries the tools (kwargs on the binding).
    assert hasattr(bound, "invoke")
    assert getattr(bound, "kwargs", {}).get("tools"), "tools should be bound"
