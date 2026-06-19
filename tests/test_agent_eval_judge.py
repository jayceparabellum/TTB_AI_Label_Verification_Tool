"""U4 — record-time LLM-judge + gate threshold check.

The judge runs at record time with the configured model; here it's MOCKED so no
credits are spent. We assert: a mocked judge bakes {faithfulness, clarity,
justification} into the snapshot; the gate passes when stored scores clear the
threshold and fails when one is below; and the gate performs NO model call (judge
is record-time only — plan D3).
"""

from __future__ import annotations

from eval import agent_cases as AC
from eval import agent_judge as J
from eval import run_agent_eval as R


class _FakeJudgeLLM:
    """Stub model returning a fixed JSON score; records that it was invoked."""

    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def invoke(self, prompt):
        self.calls += 1

        class _Msg:
            content = self.reply
        return _Msg()


def _verify_snap(message="The label FLAGs on ABV.", judge=None):
    return AC.Snapshot(
        case_id="verify_label_flag", expected_tool="verify_label",
        invariants=[AC.INV_VERDICT_VERBATIM, AC.INV_TOOL_ROUTING], is_write=False,
        transcript=[
            AC.tool_call_step("verify_label", {}),
            AC.tool_result_step("verify_label",
                                {"overall_pass": False, "needs_review": False}),
            AC.message_step(message),
        ],
        ground_truth={"overall_pass": False, "needs_review": False},
        judge=judge)


def test_judge_bakes_scores_into_snapshot():
    snap = _verify_snap()
    llm = _FakeJudgeLLM('{"faithfulness": 5, "clarity": 4, "actionability": 5, '
                        '"calibration": 4, "justification": "matches"}')
    block = J.judge_snapshot(snap, llm=llm)
    assert block == {"faithfulness": 5, "clarity": 4, "actionability": 5,
                     "calibration": 4, "justification": "matches"}
    assert llm.calls == 1


def test_judge_parses_all_four_dims():
    """_parse extracts all four rubric dimensions (the two new ones included)."""
    snap = _verify_snap()
    llm = _FakeJudgeLLM('{"faithfulness": 4, "clarity": 5, "actionability": 3, '
                        '"calibration": 2, "justification": "ok"}')
    block = J.judge_snapshot(snap, llm=llm)
    assert set(block) == {"faithfulness", "clarity", "actionability",
                          "calibration", "justification"}
    assert block["actionability"] == 3 and block["calibration"] == 2


def test_judge_handles_missing_new_dims_gracefully():
    """A reply that omits some dims still parses the ones present (no crash)."""
    snap = _verify_snap()
    llm = _FakeJudgeLLM('{"faithfulness": 4, "clarity": 5}')
    block = J.judge_snapshot(snap, llm=llm)
    assert block == {"faithfulness": 4, "clarity": 5}
    assert "actionability" not in block and "calibration" not in block


def test_judge_parses_json_embedded_in_prose():
    snap = _verify_snap()
    llm = _FakeJudgeLLM('Here are the scores: {"faithfulness": 3, "clarity": 5} done.')
    block = J.judge_snapshot(snap, llm=llm)
    assert block["faithfulness"] == 3 and block["clarity"] == 5


def test_judge_returns_none_when_nothing_to_judge():
    # No ground truth (a pure-RAG case) -> nothing to score.
    snap = AC.Snapshot(case_id="rag", expected_tool="regulatory_lookup",
                       invariants=[AC.INV_CITE_OR_REFUSE], is_write=False,
                       transcript=[AC.message_step("See 27 CFR 16.21.")],
                       ground_truth=None)
    assert J.judge_snapshot(snap, llm=_FakeJudgeLLM("{}")) is None


def test_gate_passes_when_all_four_dims_at_or_above_threshold():
    snap = _verify_snap(judge={"faithfulness": 3, "clarity": 4, "actionability": 5,
                               "calibration": 3, "justification": "ok"})
    g = R.grade_snapshot(snap, judge_threshold=3)
    assert g["judge"][0] is True
    assert g["passed"]


def test_gate_fails_when_judge_below_threshold():
    snap = _verify_snap(judge={"faithfulness": 2, "clarity": 4, "justification": "soft"})
    g = R.grade_snapshot(snap, judge_threshold=3)
    assert g["judge"][0] is False
    assert not g["passed"]


def test_gate_threshold_checks_each_new_dim():
    """A low actionability or calibration alone fails the gate — the two new dims
    are threshold-checked, not just the original two."""
    low_action = _verify_snap(judge={"faithfulness": 5, "clarity": 5,
                                     "actionability": 2, "calibration": 5})
    g = R.grade_snapshot(low_action, judge_threshold=3)
    assert g["judge"][0] is False and "actionability" in g["judge"][1]
    assert not g["passed"]

    low_calib = _verify_snap(judge={"faithfulness": 5, "clarity": 5,
                                    "actionability": 5, "calibration": 1})
    g = R.grade_snapshot(low_calib, judge_threshold=3)
    assert g["judge"][0] is False and "calibration" in g["judge"][1]
    assert not g["passed"]


def test_gate_skips_judge_when_no_block():
    snap = _verify_snap(judge=None)
    g = R.grade_snapshot(snap)
    assert g["judge"] is None
    assert g["passed"]            # invariants still hold; judge is optional


def test_recorder_bakes_judge_block(monkeypatch):
    """Record-time integration: record_case(run_judge=True) stores the judge block."""
    from pathlib import Path

    import pytest
    from langchain_core.messages import AIMessage, ToolMessage

    from agent.images import STORE
    from eval import agent_record as REC

    samples = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
    if not (samples / "clean_pass.png").exists():
        pytest.skip("sample images not generated")
    STORE._images.clear()
    STORE.seed_samples()

    class _Call:
        def invoke(self, msgs):
            if any(isinstance(m, ToolMessage) for m in msgs):
                return AIMessage(content="PASS — everything matches.")
            return AIMessage(content="", tool_calls=[{
                "name": "verify_label",
                "args": {"brand": "Stone's Throw", "alcohol_content": "5.0"},
                "id": "c1", "type": "tool_call"}])

        def bind_tools(self, tools):
            return self

    monkeypatch.setattr(
        J, "judge_snapshot",
        lambda snap, **k: {"faithfulness": 5, "clarity": 5, "justification": "stub"})
    case = next(c for c in AC.ROSTER if c.id == "verify_label_pass")
    snap = REC.record_case(case, llm=_Call(), run_judge=True)
    assert snap.judge == {"faithfulness": 5, "clarity": 5, "justification": "stub"}


def test_gate_constructs_no_llm(monkeypatch):
    """D3: grading must never build or call a model."""
    import agent.llm as LLM

    def _boom(*a, **k):
        raise AssertionError("gate must not construct an LLM")

    monkeypatch.setattr(LLM, "make_llm", _boom)
    # also guard the judge module's bound reference
    monkeypatch.setattr(J, "make_llm", _boom)
    snap = _verify_snap(judge={"faithfulness": 5, "clarity": 5, "justification": "x"})
    g = R.grade_snapshot(snap)
    assert g["passed"]
