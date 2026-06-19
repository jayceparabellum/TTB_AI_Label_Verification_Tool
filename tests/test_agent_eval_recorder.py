"""U2 — live recorder mechanics, exercised OFFLINE with a fake LLM.

The `_Call` stub (same pattern as tests/test_agent_slice_d.py) emits a fixed tool
call on the first turn and a closing message after the tool result, so the recorder
runs the real graph with no model and no credits. We assert the snapshot's
transcript captures the tool_call + tool_result, the WRITE confirm-gate interrupt is
recorded before the tool result and the post-approve resume is captured, the
ground_truth equals the core function on the same inputs, and the snapshot
round-trips through U1's loader. A regression test asserts the recorder mutates no
agent module (PRD R8).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from agent import tools as T
from agent.images import STORE
from eval import agent_cases as AC
from eval import agent_record as REC

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(), reason="sample images not generated")


class _Call:
    """Fake LLM: emit `name(args)` once, then a closing message after the tool ran.
    `message` lets a verify case narrate the matching verdict keyword."""

    def __init__(self, name, args, message="ok"):
        self.name, self.args, self.message = name, args, message

    def invoke(self, msgs):
        if any(isinstance(m, ToolMessage) for m in msgs):
            return AIMessage(content=self.message)
        return AIMessage(content="", tool_calls=[{
            "name": self.name, "args": self.args, "id": "c1", "type": "tool_call"}])

    def bind_tools(self, tools):       # graph/make_llm compatibility
        return self


@pytest.fixture(autouse=True)
def _setup():
    STORE._images.clear()
    STORE.seed_samples()
    T.LAST_BATCH = None
    yield
    T.LAST_BATCH = None


def _case(case_id):
    return next(c for c in AC.ROSTER if c.id == case_id)


def test_records_verify_label_transcript_and_ground_truth():
    case = _case("verify_label_flag")
    llm = _Call("verify_label",
                {"brand": "Stone's Throw", "alcohol_content": "5.0"},
                message="The label FLAGs on alcohol content.")
    snap = REC.record_case(case, llm=llm, run_judge=False)

    calls = [s for s in snap.transcript if s["kind"] == AC.KIND_TOOL_CALL]
    results = [s for s in snap.transcript if s["kind"] == AC.KIND_TOOL_RESULT]
    assert [c["tool"] for c in calls] == ["verify_label"]
    assert results and results[0]["tool"] == "verify_label"

    # Ground truth equals run_verify on the same inputs (verdict fields; timing
    # jitter aside). The recorder stores the live core result for this case.
    from eval.run_agent_eval import _verdict_eq
    gt = T.run_verify("abv_mismatch", "Stone's Throw", "5.0")
    assert _verdict_eq(snap.ground_truth, gt)
    assert snap.ground_truth["overall_pass"] == gt["overall_pass"]
    # The recorded tool result matches that ground truth too (verbatim contract).
    assert _verdict_eq(results[0]["result"], snap.ground_truth)


def test_write_case_records_interrupt_then_resume():
    case = _case("batch_verify_gated")
    snap = REC.record_case(case, llm=_Call("batch_verify", {}), run_judge=False)

    kinds = [s["kind"] for s in snap.transcript]
    assert AC.KIND_INTERRUPT in kinds, "WRITE must record a confirm-gate interrupt"
    # interrupt precedes the batch_verify tool result (resume captured the rest).
    intr_i = kinds.index(AC.KIND_INTERRUPT)
    res_i = next(i for i, s in enumerate(snap.transcript)
                 if s["kind"] == AC.KIND_TOOL_RESULT and s["tool"] == "batch_verify")
    assert intr_i < res_i
    assert T.LAST_BATCH is not None       # the resume actually executed the write


def test_override_result_write_records_interrupt_then_resume():
    """The override_result WRITE case records the confirm-gate interrupt before the
    tool executes, and the post-approve resume captures the override result."""
    case = _case("override_result_gated")
    llm = _Call(
        "override_result",
        {"result_id": "r1", "new_status": "PASS",
         "reason": "ABV reads correctly on the physical sample; scanner misread."},
        message="I've recorded your override to PASS.")
    snap = REC.record_case(case, llm=llm, run_judge=False)

    kinds = [s["kind"] for s in snap.transcript]
    assert AC.KIND_INTERRUPT in kinds, "WRITE must record a confirm-gate interrupt"
    intr_i = kinds.index(AC.KIND_INTERRUPT)
    res_i = next(i for i, s in enumerate(snap.transcript)
                 if s["kind"] == AC.KIND_TOOL_RESULT and s["tool"] == "override_result")
    assert intr_i < res_i, "interrupt must precede the override result"
    # The resume actually executed the write (audit row recorded).
    result = snap.transcript[res_i]["result"]
    assert result.get("ok") is True and result.get("new_status") == "PASS"


def test_recorder_snapshot_round_trips(tmp_path):
    case = _case("verify_label_pass")
    llm = _Call("verify_label", {"brand": "Stone's Throw", "alcohol_content": "5.0"},
                message="PASS — everything matches.")
    snap = REC.record_case(case, llm=llm, run_judge=False)
    path = AC.dump(snap, tmp_path / f"{case.id}.json")
    assert AC.load(path).to_dict() == snap.to_dict()


def test_recorded_verify_pass_grades_clean():
    """End-to-end: a fake-LLM recording of the PASS case passes the U3 gate."""
    from eval import run_agent_eval as R
    case = _case("verify_label_pass")
    llm = _Call("verify_label", {"brand": "Stone's Throw", "alcohol_content": "5.0"},
                message="PASS — brand, ABV, and warning all match.")
    snap = REC.record_case(case, llm=llm, run_judge=False)
    g = R.grade_snapshot(snap)
    assert g["passed"], g["invariants"]


def test_recorder_mutates_no_agent_module():
    """R8: the recorder imports + drives only; it does not monkeypatch agent code."""
    import agent.graph as G
    import agent.confirm as C
    before = (G.build_graph, C.confirm_gate, T.run_verify, T.verify_label)
    REC.record_case(_case("verify_label_pass"),
                    llm=_Call("verify_label",
                              {"brand": "Stone's Throw", "alcohol_content": "5.0"},
                              message="PASS."),
                    run_judge=False)
    assert (G.build_graph, C.confirm_gate, T.run_verify, T.verify_label) == before


def test_run_record_writes_subset_to_dir(tmp_path):
    """run_record over a single case writes a schema-valid snapshot file."""
    # Patch make_llm so no live backend is touched.
    import eval.agent_record as mod
    mod_make = mod.make_llm
    try:
        mod.make_llm = lambda *a, **k: _Call(
            "verify_label", {"brand": "Stone's Throw", "alcohol_content": "5.0"},
            message="PASS.")
        code = mod.run_record(snapshot_dir=tmp_path, only=["verify_label_pass"],
                              run_judge=False)
    finally:
        mod.make_llm = mod_make
    assert code == 0
    files = list(tmp_path.glob("*.json"))
    assert [p.name for p in files] == ["verify_label_pass.json"]
    AC.load(files[0])      # loads without error
