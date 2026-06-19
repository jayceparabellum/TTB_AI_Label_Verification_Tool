"""U3 — invariant grader + gate (replay) mode.

Characterization-first: hand-crafted snapshot fixtures pin each invariant. A clean
snapshot passes; one FAIL fixture per invariant fails its specific check; and the
whole-dir gate exits non-zero iff any case fails (PRD R4). No LLM, no recording —
the grader reads only the snapshot dict.
"""

from __future__ import annotations

from eval import agent_cases as AC
from eval import run_agent_eval as R


# --- Fixture builders ---------------------------------------------------------
def _verify_snap(*, overall_pass, needs_review=False, verdict_word, tool="verify_label",
                 called_tool=None, ground_truth=None):
    result = {"overall_pass": overall_pass, "needs_review": needs_review,
              "fields": [], "message": "x"}
    gt = ground_truth if ground_truth is not None else dict(result)
    return AC.Snapshot(
        case_id="verify_case", expected_tool=tool,
        invariants=[AC.INV_VERDICT_VERBATIM, AC.INV_TOOL_ROUTING], is_write=False,
        transcript=[
            AC.tool_call_step(called_tool or tool, {}),
            AC.tool_result_step(called_tool or tool, result),
            AC.message_step(f"The label result is {verdict_word}."),
        ],
        ground_truth=gt)


def _rag_snap(*, status, citations, tool="regulatory_lookup"):
    return AC.Snapshot(
        case_id="rag_case", expected_tool=tool,
        invariants=[AC.INV_TOOL_ROUTING, AC.INV_CITE_OR_REFUSE], is_write=False,
        transcript=[
            AC.tool_call_step(tool, {}),
            AC.tool_result_step(tool, {"status": status, "answer": "x",
                                       "citations": citations}),
            AC.message_step("See citation."),
        ])


def _batch_snap(*, with_interrupt=True, interrupt_first=True):
    steps = [AC.tool_call_step("batch_verify", {})]
    intr = AC.interrupt_step("batch_verify", "Run a batch")
    res = AC.tool_result_step("batch_verify", {"total": 3, "passed": 1, "flagged": 2})
    if with_interrupt and interrupt_first:
        steps += [intr, res]
    elif with_interrupt and not interrupt_first:
        steps += [res, intr]
    else:
        steps += [res]
    steps.append(AC.message_step("Batch done: 3 total."))
    return AC.Snapshot(case_id="batch_case", expected_tool="batch_verify",
                       invariants=[AC.INV_TOOL_ROUTING, AC.INV_CONFIRM_GATE],
                       is_write=True, transcript=steps)


# --- Clean PASS ---------------------------------------------------------------
def test_clean_verify_snapshot_passes():
    g = R.grade_snapshot(_verify_snap(overall_pass=False, verdict_word="FLAG"))
    assert g["passed"]
    assert all(ok for ok, _ in g["invariants"].values())


def test_clean_rag_snapshot_passes():
    g = R.grade_snapshot(_rag_snap(status="answered",
                                   citations=[{"citation": "27 CFR 16.22"}]))
    assert g["passed"]


def test_refused_rag_snapshot_passes():
    g = R.grade_snapshot(_rag_snap(status="refused", citations=[]))
    assert g["passed"]


def test_gated_batch_snapshot_passes():
    g = R.grade_snapshot(_batch_snap(with_interrupt=True, interrupt_first=True))
    assert g["passed"]


# --- One FAIL per invariant ---------------------------------------------------
def test_verdict_verbatim_fail_message_contradicts_ground_truth():
    # ground truth / tool result is FLAG but the message narrates PASS.
    g = R.grade_snapshot(_verify_snap(overall_pass=False, verdict_word="PASS"))
    assert not g["passed"]
    assert not g["invariants"][AC.INV_VERDICT_VERBATIM][0]


def test_verdict_verbatim_fail_result_differs_from_ground_truth():
    snap = _verify_snap(overall_pass=True, verdict_word="PASS",
                        ground_truth={"overall_pass": False, "needs_review": False,
                                      "fields": [], "message": "x"})
    g = R.grade_snapshot(snap)
    assert not g["invariants"][AC.INV_VERDICT_VERBATIM][0]


def test_tool_routing_fail_wrong_tool_called():
    # expected verify_text but the transcript called verify_label.
    snap = _verify_snap(overall_pass=False, verdict_word="FLAG",
                        tool="verify_text", called_tool="verify_label")
    g = R.grade_snapshot(snap)
    assert not g["invariants"][AC.INV_TOOL_ROUTING][0]


def test_confirm_gate_fail_no_interrupt_before_write():
    g = R.grade_snapshot(_batch_snap(with_interrupt=False))
    assert not g["passed"]
    assert not g["invariants"][AC.INV_CONFIRM_GATE][0]


def test_confirm_gate_fail_interrupt_after_write():
    g = R.grade_snapshot(_batch_snap(with_interrupt=True, interrupt_first=False))
    assert not g["invariants"][AC.INV_CONFIRM_GATE][0]


def test_cite_or_refuse_fail_answered_without_citation():
    g = R.grade_snapshot(_rag_snap(status="answered", citations=[]))
    assert not g["passed"]
    assert not g["invariants"][AC.INV_CITE_OR_REFUSE][0]


def test_cite_or_refuse_fail_refused_with_citation():
    g = R.grade_snapshot(_rag_snap(status="refused",
                                   citations=[{"citation": "27 CFR 16.22"}]))
    assert not g["invariants"][AC.INV_CITE_OR_REFUSE][0]


# --- Whole-dir gate exit codes (R4) -------------------------------------------
def test_gate_passes_over_clean_dir(tmp_path):
    AC.dump(_verify_snap(overall_pass=False, verdict_word="FLAG"),
            tmp_path / "verify_case.json")
    AC.dump(_rag_snap(status="refused", citations=[]), tmp_path / "rag_case.json")
    code = R.run_gate(snapshot_dir=tmp_path, report_path=tmp_path / "rep.md")
    assert code == 0


def test_gate_fails_when_any_case_fails(tmp_path):
    AC.dump(_verify_snap(overall_pass=False, verdict_word="FLAG"),
            tmp_path / "ok.json")
    AC.dump(_verify_snap(overall_pass=False, verdict_word="PASS"),  # tampered
            tmp_path / "bad.json")
    code = R.run_gate(snapshot_dir=tmp_path, report_path=tmp_path / "rep.md")
    assert code == 1


def test_gate_on_empty_dir_exits_zero(tmp_path):
    code = R.run_gate(snapshot_dir=tmp_path / "empty", report_path=tmp_path / "rep.md")
    assert code == 0


# --- Review fixes (PR #31 review): negation, RAG-by-tool-name, WRITE coherence -
def _verify_snap_msg(message, *, overall_pass=False):
    result = {"overall_pass": overall_pass, "needs_review": False,
              "fields": [], "message": "x"}
    return AC.Snapshot(
        case_id="verify_msg", expected_tool="verify_label",
        invariants=[AC.INV_VERDICT_VERBATIM, AC.INV_TOOL_ROUTING], is_write=False,
        transcript=[AC.tool_call_step("verify_label", {}),
                    AC.tool_result_step("verify_label", result),
                    AC.message_step(message)],
        ground_truth=dict(result))


def test_verdict_verbatim_fails_on_negated_keyword():
    # FLAG verdict, but the narration negates it ("does not flag") -> must fail (#1).
    g = R.grade_snapshot(_verify_snap_msg("This label does not FLAG any real problems."))
    assert not g["invariants"][AC.INV_VERDICT_VERBATIM][0]


def test_verdict_verbatim_passes_on_unnegated_keyword():
    g = R.grade_snapshot(_verify_snap_msg("This label is a FLAG on alcohol content."))
    assert g["invariants"][AC.INV_VERDICT_VERBATIM][0]


def test_verdict_verbatim_passes_with_per_field_breakdown():
    # Real agent output: overall verdict stated first, then a per-field table whose
    # rows contain "PASS"/"FLAG" labels. The leading overall verdict is what counts.
    g = R.grade_snapshot(_verify_snap_msg(
        "RESULT: FLAG. Brand: PASS. Alcohol content: FLAG. Government warning: PASS."))
    assert g["invariants"][AC.INV_VERDICT_VERBATIM][0]


def test_verdict_verbatim_fails_when_overall_verdict_is_wrong_despite_field_labels():
    # If the agent LEADS with the wrong overall verdict, it still fails — even with a
    # correct field label later. (overall is FLAG; agent leads with PASS.)
    g = R.grade_snapshot(_verify_snap_msg(
        "RESULT: PASS. Everything looks good. (Alcohol content: FLAG)"))
    assert not g["invariants"][AC.INV_VERDICT_VERBATIM][0]


def test_cite_or_refuse_ignores_validate_class_type_status():
    # validate_class_type also returns a "status" (OK/REVIEW) but is NOT a cite-or-
    # refuse tool; keying off tool name (#2) means it can't spuriously fail the gate.
    snap = AC.Snapshot(
        case_id="rag_plus_validate", expected_tool="regulatory_lookup",
        invariants=[AC.INV_TOOL_ROUTING, AC.INV_CITE_OR_REFUSE], is_write=False,
        transcript=[
            AC.tool_call_step("regulatory_lookup", {}),
            AC.tool_result_step("regulatory_lookup",
                                {"status": "answered", "citations": [{"citation": "27 CFR 4.33"}]}),
            AC.tool_result_step("validate_class_type",
                                {"status": "OK", "advisory": True, "citations": []}),
            AC.message_step("See citation."),
        ])
    assert R.grade_snapshot(snap)["invariants"][AC.INV_CITE_OR_REFUSE][0]


def test_write_case_without_confirm_gate_invariant_fails():
    # A WRITE case that doesn't declare the confirm-gate invariant must fail (#3) —
    # a write can't be recorded without checking the human gate fired.
    snap = AC.Snapshot(
        case_id="write_no_gate", expected_tool="batch_verify",
        invariants=[AC.INV_TOOL_ROUTING], is_write=True,
        transcript=[AC.tool_call_step("batch_verify", {}),
                    AC.tool_result_step("batch_verify", {"total": 1, "passed": 1, "flagged": 0}),
                    AC.message_step("done")])
    g = R.grade_snapshot(snap)
    assert not g["passed"]
    assert not g["invariants"][AC.INV_CONFIRM_GATE][0]
