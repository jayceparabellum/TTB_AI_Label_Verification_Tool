"""U4 — confirm gate / interrupt-resume at the graph level: writes pause for human
approval, reads flow through, approve executes once, cancel writes nothing, and
threads are isolated."""

import sqlite3

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agent import audit, config
from agent.graph import build_graph


@pytest.fixture(autouse=True)
def _tmp_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_DB", tmp_path / "audit.sqlite")
    yield


def _graph(stub):
    return build_graph(llm=stub, checkpointer=SqliteSaver(
        sqlite3.connect(":memory:", check_same_thread=False)))


class _WriteStub:
    def invoke(self, msgs):
        if any(isinstance(m, ToolMessage) for m in msgs):
            return AIMessage(content="done")
        return AIMessage(content="", tool_calls=[{
            "name": "override_result",
            "args": {"result_id": "r1", "new_status": "PASS", "reason": "manual ok"},
            "id": "w1", "type": "tool_call"}])


class _ReadStub:
    def invoke(self, msgs):
        if any(isinstance(m, ToolMessage) for m in msgs):
            return AIMessage(content="reported")
        return AIMessage(content="", tool_calls=[{
            "name": "verify_label",
            "args": {"brand": "Stone's Throw", "alcohol_content": "5.0"},
            "id": "r1", "type": "tool_call"}])


def _start(g, thread):
    return list(g.stream(
        {"messages": [HumanMessage("override r1 to pass")],
         "active_image_id": "clean_pass", "expected": None, "last_result_id": "r1"},
        {"configurable": {"thread_id": thread}}, stream_mode="updates"))


def test_write_pauses_before_executing():
    g = _graph(_WriteStub())
    updates = _start(g, "t1")
    assert any("__interrupt__" in u for u in updates)   # paused
    assert audit.recent() == []                          # nothing written yet


def test_resume_approve_executes_exactly_once():
    g = _graph(_WriteStub())
    _start(g, "t1")
    list(g.stream(Command(resume="approve"), {"configurable": {"thread_id": "t1"}}))
    assert len(audit.recent()) == 1 and audit.recent()[0]["new_verdict"] == "PASS"


def test_resume_cancel_writes_nothing():
    g = _graph(_WriteStub())
    _start(g, "t1")
    out = list(g.stream(Command(resume="cancel"),
                        {"configurable": {"thread_id": "t1"}}, stream_mode="updates"))
    assert audit.recent() == []
    assert "cancel" in str(out).lower()                  # cancellation surfaced


def test_read_tool_does_not_interrupt():
    g = _graph(_ReadStub())
    updates = list(g.stream(
        {"messages": [HumanMessage("verify the label")], "active_image_id": "clean_pass",
         "expected": None, "last_result_id": None},
        {"configurable": {"thread_id": "t1"}}, stream_mode="updates"))
    assert not any("__interrupt__" in u for u in updates)


def test_thread_isolation():
    g = _graph(_WriteStub())
    _start(g, "a")          # both threads pause at their own interrupt
    _start(g, "b")
    list(g.stream(Command(resume="approve"), {"configurable": {"thread_id": "a"}}))
    assert len(audit.recent()) == 1     # only thread 'a' wrote; 'b' still paused
