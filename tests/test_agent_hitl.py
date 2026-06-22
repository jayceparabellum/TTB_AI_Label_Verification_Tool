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


class _MultiWriteStub:
    """Emits TWO write calls in one turn — the multi-write confirm-gate case."""

    def invoke(self, msgs):
        if any(isinstance(m, ToolMessage) for m in msgs):
            return AIMessage(content="done")
        return AIMessage(content="", tool_calls=[
            {"name": "override_result",
             "args": {"result_id": "r1", "new_status": "PASS", "reason": "ok one"},
             "id": "w1", "type": "tool_call"},
            {"name": "override_result",
             "args": {"result_id": "r2", "new_status": "FLAG", "reason": "ok two"},
             "id": "w2", "type": "tool_call"},
        ])


def _start(g, thread):
    return list(g.stream(
        {"messages": [HumanMessage("override r1 to pass")],
         "active_image_id": "clean_pass", "expected": None, "last_result_id": "r1"},
        {"configurable": {"thread_id": thread}}, stream_mode="updates"))


def _interrupt_payload(updates):
    """Pull the confirm-interrupt payload dict out of streamed updates."""
    for u in updates:
        if "__interrupt__" in u:
            return u["__interrupt__"][0].value
    return None


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


def test_single_write_payload_lists_one_action():
    g = _graph(_WriteStub())
    payload = _interrupt_payload(_start(g, "t1"))
    assert payload["action"] == "override_result"        # single-write shape preserved
    assert len(payload["actions"]) == 1
    assert payload["summary"] == payload["actions"][0]["summary"]


def test_multi_write_confirm_surfaces_every_pending_write():
    # The gap this guards: approving runs ToolNode over ALL tool calls, so a turn
    # with two writes executes both — the human must see both, not just the first.
    g = _graph(_MultiWriteStub())
    payload = _interrupt_payload(_start(g, "t1"))
    assert len(payload["actions"]) == 2
    assert {a["args"]["result_id"] for a in payload["actions"]} == {"r1", "r2"}
    assert "2 actions" in payload["summary"]
    assert "r1" in payload["summary"] and "r2" in payload["summary"]


def test_multi_write_approve_executes_all_then_cancel_writes_nothing():
    g = _graph(_MultiWriteStub())
    _start(g, "approve-thread")
    list(g.stream(Command(resume="approve"),
                  {"configurable": {"thread_id": "approve-thread"}}))
    assert len(audit.recent()) == 2                      # both writes ran on approve

    g2 = _graph(_MultiWriteStub())
    _start(g2, "cancel-thread")
    list(g2.stream(Command(resume="cancel"),
                   {"configurable": {"thread_id": "cancel-thread"}}))
    assert len(audit.recent()) == 2                      # cancel added nothing


def test_thread_isolation():
    g = _graph(_WriteStub())
    _start(g, "a")          # both threads pause at their own interrupt
    _start(g, "b")
    list(g.stream(Command(resume="approve"), {"configurable": {"thread_id": "a"}}))
    assert len(audit.recent()) == 1     # only thread 'a' wrote; 'b' still paused
