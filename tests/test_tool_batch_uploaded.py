"""U5 — batch_verify over an UPLOADED CSV + images (not just the seeded samples).
The chat path runs the same deterministic core (app.batch.run_batch) as the Batch
page; parity is asserted. Stays a WRITE tool behind the confirm gate, the summary
reflects the uploaded set, and a results CSV is returned for download."""

import sqlite3
from pathlib import Path

import base64
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app import batch as _batch
from agent import config, confirm
from agent import tools as T
from agent.graph import build_graph
from agent.images import STAGING, STORE

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(), reason="sample images not generated")


@pytest.fixture(autouse=True)
def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_DB", tmp_path / "audit.sqlite")
    T.LAST_BATCH = None
    STORE._images.clear()
    STAGING._by_thread.clear()
    yield
    T.LAST_BATCH = None
    STAGING._by_thread.clear()


def _png(name):
    return (SAMPLES / name).read_bytes()


# Custom filenames (NOT the sample filenames) so a fallback-to-samples run would
# produce different rows — proving the uploaded set, not the samples, was used.
UP_IMAGES = [("good_one.png", _png("clean_pass.png")),
             ("wrong_abv.png", _png("abv_mismatch.png"))]
UP_CSV = (b"filename,brand,alcohol_content\n"
          b"good_one.png,Stone's Throw,5.0\n"
          b"wrong_abv.png,Stone's Throw,5.0\n")


def _stage(thread):
    for name, data in UP_IMAGES:
        STAGING.add_batch_image(thread, name, data)
    STAGING.set_batch_csv(thread, UP_CSV)


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
        {"messages": [HumanMessage("go")], "active_image_id": None, "expected": None,
         "last_result_id": None, "thread_id": thread},
        {"configurable": {"thread_id": thread}}, stream_mode="updates"))
    return g, out


def test_uploaded_batch_runs_over_uploaded_set_and_matches_core():
    _stage("t")
    g, out = _run("batch_verify", {}, thread="t")
    assert any("__interrupt__" in u for u in out)            # WRITE -> gated
    assert T.LAST_BATCH is None                              # nothing ran yet
    list(g.stream(Command(resume="approve"), {"configurable": {"thread_id": "t"}}))

    # Parity: the chat path's batch equals run_batch() over the SAME uploaded set.
    core = _batch.run_batch(UP_IMAGES, UP_CSV)
    got = {r.filename: r.status for r in T.LAST_BATCH.rows}
    expected = {r.filename: r.status for r in core.rows}
    assert got == expected
    assert "good_one.png" in got and "wrong_abv.png" in got   # uploaded, not samples


def test_uploaded_batch_tool_returns_summary_source_and_results_csv():
    _stage("t2")
    out = T.batch_verify.invoke({"state": {"thread_id": "t2"}})
    assert out["source"] == "uploaded"
    assert out["total"] == 2 and out["flagged"] >= 1          # wrong_abv flags
    # The download payload is exactly the core's results CSV.
    decoded = base64.b64decode(out["results_csv_b64"]).decode()
    assert decoded == _batch.results_to_csv(T.LAST_BATCH)


def test_no_staged_batch_falls_back_to_samples():
    out = T.batch_verify.invoke({"state": {"thread_id": "empty-thread"}})
    assert out["source"] == "samples" and out["total"] >= 3


def test_cancel_leaves_last_batch_untouched():
    _stage("t3")
    g, _out = _run("batch_verify", {}, thread="t3")
    list(g.stream(Command(resume="cancel"), {"configurable": {"thread_id": "t3"}}))
    assert T.LAST_BATCH is None                               # cancel ran nothing


def test_over_cap_upload_surfaces_core_error_no_crash():
    thread = "tcap"
    png = _png("clean_pass.png")
    rows = ["filename,brand,alcohol_content"]
    for i in range(_batch.BATCH_MAX_LABELS + 3):
        STAGING.add_batch_image(thread, f"x{i}.png", png)
        rows.append(f"x{i}.png,Stone's Throw,5.0")
    STAGING.set_batch_csv(thread, ("\n".join(rows)).encode())
    out = T.batch_verify.invoke({"state": {"thread_id": thread}})
    assert "error" in out and "split" in out["error"].lower()  # cap message, no verdict
    assert "total" not in out


def test_list_flagged_reflects_uploaded_batch():
    _stage("t4")
    T.batch_verify.invoke({"state": {"thread_id": "t4"}})
    lf = T.list_flagged.invoke({})
    assert "wrong_abv.png" in {f["filename"] for f in lf["flagged"]}


def test_confirm_summary_reflects_uploaded_count():
    _stage("t5")
    call = {"name": "batch_verify", "args": {}}
    assert confirm._summary(call, {"thread_id": "t5"}) == "Run a batch over 2 uploaded labels"
    # No staged batch -> the samples wording.
    assert "sample" in confirm._summary(call, {"thread_id": "none"}).lower()
