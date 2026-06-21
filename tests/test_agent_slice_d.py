"""Slice D — should-have tools: conversational batch control (gated batch_verify
-> list_flagged) and advisory validate_class_type (OK|REVIEW, never auto-reject)."""

import sqlite3
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agent import config
from agent import tools as T
from agent.graph import build_graph
from agent.images import STORE

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(), reason="sample images not generated")


@pytest.fixture(autouse=True)
def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_DB", tmp_path / "audit.sqlite")
    T.LAST_BATCH = None
    STORE._images.clear()
    STORE.seed_samples()
    yield
    T.LAST_BATCH = None


class _Call:
    def __init__(self, name, args):
        self.name, self.args = name, args

    def invoke(self, msgs):
        if any(isinstance(m, ToolMessage) for m in msgs):
            return AIMessage(content="ok")
        return AIMessage(content="", tool_calls=[{
            "name": self.name, "args": self.args, "id": "c1", "type": "tool_call"}])


def _run(name, args, thread="t"):
    g = build_graph(llm=_Call(name, args),
                    checkpointer=SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False)))
    out = list(g.stream(
        {"messages": [HumanMessage("go")], "active_image_id": None,
         "expected": None, "last_result_id": None},
        {"configurable": {"thread_id": thread}}, stream_mode="updates"))
    return g, out


def test_roster_size():
    assert len(T.ALL_TOOLS) == 13
    assert "batch_verify" in T.WRITE_TOOL_NAMES
    read_names = {t.name for t in T.READ_TOOLS}
    assert "validate_class_type" in read_names and "verify_audit_log" in read_names


def test_batch_verify_is_gated_then_populates_list_flagged():
    g, out = _run("batch_verify", {})
    assert any("__interrupt__" in u for u in out)     # expensive op -> gated
    assert T.LAST_BATCH is None
    list(g.stream(Command(resume="approve"), {"configurable": {"thread_id": "t"}}))
    assert T.LAST_BATCH is not None
    lf = T.list_flagged.invoke({})
    assert lf["count"] >= 2                            # abv_mismatch + bad_warning flag
    assert "abv_mismatch.png" in {f["filename"] for f in lf["flagged"]}


def test_batch_verify_cancel_runs_nothing():
    g, _out = _run("batch_verify", {})
    list(g.stream(Command(resume="cancel"), {"configurable": {"thread_id": "t"}}))
    assert T.LAST_BATCH is None


def test_validate_class_type_is_advisory_with_citation():
    ok = T.validate_class_type.invoke({"claimed_designation": "table wine",
                                       "beverage_type": "wine"})
    assert ok["status"] == "OK" and ok["advisory"] is True and ok["citations"]
    review = T.validate_class_type.invoke({"claimed_designation": "Moon Juice Extreme",
                                           "beverage_type": "wine"})
    assert review["status"] == "REVIEW" and review["advisory"] is True
    # Advisory only — never an automatic rejection.
    assert ok["status"] in {"OK", "REVIEW"} and review["status"] in {"OK", "REVIEW"}
