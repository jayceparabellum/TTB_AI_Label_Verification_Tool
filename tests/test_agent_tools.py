"""Agent shell — full tool roster: reads flow through, manual_fallback is gated +
audited, RAG tools are refusing stubs, and the write set is correct."""

import sqlite3
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agent import audit, config
from agent import tools as T
from agent.graph import build_graph
from agent.images import STORE

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(), reason="sample images not generated")


@pytest.fixture(autouse=True)
def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_DB", tmp_path / "audit.sqlite")
    STORE._images.clear()
    STORE.seed_samples()
    yield
    STORE._images.clear()


class _Call:
    def __init__(self, name, args):
        self.name, self.args = name, args

    def invoke(self, msgs):
        if any(isinstance(m, ToolMessage) for m in msgs):
            return AIMessage(content="ok")
        return AIMessage(content="", tool_calls=[{
            "name": self.name, "args": self.args, "id": "c1", "type": "tool_call"}])


def _run_tool(name, args, image="clean_pass", thread="t"):
    g = build_graph(llm=_Call(name, args),
                    checkpointer=SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False)))
    out = list(g.stream(
        {"messages": [HumanMessage("go")], "active_image_id": image,
         "expected": None, "last_result_id": "r1"},
        {"configurable": {"thread_id": thread}}, stream_mode="updates"))
    return g, out


def test_roster_shape():
    assert len(T.ALL_TOOLS) == 13
    assert T.WRITE_TOOL_NAMES == {"override_result", "manual_fallback", "batch_verify"}
    names = {t.name for t in T.ALL_TOOLS}
    assert {"verify_label", "verify_text", "extract_label_fields", "verify_warning",
            "list_flagged", "regulatory_lookup", "explain_flag", "validate_class_type",
            "export_audit_log", "verify_audit_log"} <= names


def test_validate_class_type_grounds_in_dataset():
    ok = T.validate_class_type.invoke({"claimed_designation": "Bourbon"})
    assert ok["status"] == "OK" and ok["advisory"] is True       # spirits, inferred
    wine = T.validate_class_type.invoke({"claimed_designation": "Cabernet Sauvignon"})
    assert wine["status"] == "OK"
    rev = T.validate_class_type.invoke({"claimed_designation": "Unicorn Tears"})
    assert rev["status"] == "REVIEW"                              # not a recognized class/type


def test_verify_audit_log_reports_integrity():
    audit.record("agent-user", "override", "r1", "FLAG", "PASS", "manual review ok")
    intact = T.verify_audit_log.invoke({})
    assert intact["ok"] and intact["kind"] is None

    # Tamper out-of-band, then the tool reports the break (read-only; no confirm gate).
    from sqlalchemy import text
    with audit._engine().begin() as c:
        c.execute(text("UPDATE audit SET reason = 'tampered' WHERE id = 1"))
    broken = T.verify_audit_log.invoke({})
    assert not broken["ok"] and broken["kind"] == "altered"


def test_read_tools_flow_through_without_interrupt():
    for name in ("extract_label_fields", "verify_warning"):
        _g, out = _run_tool(name, {})
        assert not any("__interrupt__" in u for u in out), f"{name} must not pause"
        assert "readable" in str(out) or "passed" in str(out)


def test_list_flagged_no_batch_is_friendly():
    out = T.list_flagged.invoke({})
    assert out["flagged"] == [] and "No batch" in out["note"]


def test_rag_tools_are_grounded_cite_or_refuse():
    # In-corpus -> answered with a citation; out-of-corpus -> refused (no memory).
    rl = T.regulatory_lookup.invoke({"question": "what does a wine label need?",
                                     "beverage_type": "wine"})
    assert rl["status"] == "answered" and rl["citations"]
    refused = T.regulatory_lookup.invoke({"question": "how do I bake sourdough bread"})
    assert refused["status"] == "refused" and refused["citations"] == []
    ef = T.explain_flag.invoke({"field": "government_warning",
                                "failure_reason": "header is Title case not ALL CAPS"})
    assert ef["status"] == "answered" and ef["citations"][0]["section"] == "16.22"


def test_manual_fallback_is_gated_then_audited():
    g, out = _run_tool("manual_fallback", {"field": "abv", "value": "5.0"})
    assert any("__interrupt__" in u for u in out)        # write -> paused
    assert audit.recent() == []
    list(g.stream(Command(resume="approve"), {"configurable": {"thread_id": "t"}}))
    rows = audit.recent()
    assert len(rows) == 1 and rows[0]["action"] == "manual_entry"
    assert "abv" in rows[0]["new_verdict"]


def test_manual_fallback_empty_value_writes_nothing():
    g, _out = _run_tool("manual_fallback", {"field": "abv", "value": "   "})
    list(g.stream(Command(resume="approve"), {"configurable": {"thread_id": "t"}}))
    assert audit.recent() == []          # empty value -> tool errored, no write
