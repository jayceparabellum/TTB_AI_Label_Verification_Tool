"""U5 — report rendering + the gate CLI entrypoint.

The report renders a row per case (per-invariant pass/fail + judge), the gate exits
0 over a passing snapshot dir and writes AGENT_REPORT.md, exits non-zero over a
failing dir, and the argparse CLI routes `gate` (the free default) without touching
a model.
"""

from __future__ import annotations

from eval import agent_cases as AC
from eval import run_agent_eval as R


def _pass_snap(case_id="verify_label_flag"):
    return AC.Snapshot(
        case_id=case_id, expected_tool="verify_label",
        invariants=[AC.INV_VERDICT_VERBATIM, AC.INV_TOOL_ROUTING], is_write=False,
        transcript=[
            AC.tool_call_step("verify_label", {}),
            AC.tool_result_step("verify_label",
                                {"overall_pass": False, "needs_review": False}),
            AC.message_step("This label FLAGs on ABV."),
        ],
        ground_truth={"overall_pass": False, "needs_review": False},
        judge={"faithfulness": 5, "clarity": 4, "justification": "ok"})


def _fail_snap():
    snap = _pass_snap(case_id="tampered")
    # narrate PASS though the verdict is FLAG -> verdict-verbatim fails.
    snap.transcript[-1] = AC.message_step("This label PASSes, all good.")
    return snap


def test_report_renders_a_row_per_case_with_invariants_and_judge():
    graded = R.grade_all([_pass_snap("a"), _fail_snap()])
    report = R.render_report(graded)
    assert "| a |" in report
    assert "| tampered |" in report
    # header lists each invariant column + judge
    assert "verbatim" in report and "routing" in report
    assert "confirm-gate" in report and "cite/refuse" in report and "judge" in report
    assert "✅ PASS" in report and "❌ FAIL" in report
    # the failure is itemized with its invariant
    assert "verdict_verbatim" in report
    assert "1/2" in report          # cases passing summary


def test_report_on_empty_set_explains_recording():
    report = R.render_report([])
    assert "No snapshots recorded yet" in report
    assert "record" in report


def test_gate_writes_report_and_exits_zero_over_passing_dir(tmp_path):
    AC.dump(_pass_snap("c1"), tmp_path / "c1.json")
    rep = tmp_path / "AGENT_REPORT.md"
    code = R.run_gate(snapshot_dir=tmp_path, report_path=rep)
    assert code == 0
    assert rep.exists() and "| c1 |" in rep.read_text()


def test_gate_exits_nonzero_over_failing_dir(tmp_path):
    AC.dump(_pass_snap("good"), tmp_path / "good.json")
    AC.dump(_fail_snap(), tmp_path / "tampered.json")
    code = R.run_gate(snapshot_dir=tmp_path, report_path=tmp_path / "rep.md")
    assert code == 1


def test_cli_gate_subcommand_routes_to_gate(tmp_path, monkeypatch):
    AC.dump(_pass_snap("c1"), tmp_path / "c1.json")
    rep = tmp_path / "rep.md"
    # default to gate path; assert no LLM is constructed.
    import agent.llm as LLM
    monkeypatch.setattr(LLM, "make_llm",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("gate must not build an LLM")))
    code = R.main(["gate", "--snapshots", str(tmp_path)])
    # main() writes the default report path; just assert the exit code.
    assert code == 0


def test_cli_defaults_to_gate_with_no_subcommand(monkeypatch, tmp_path):
    # No subcommand -> gate over the (empty) default dir -> exit 0.
    monkeypatch.chdir(tmp_path)
    code = R.main([])
    assert code == 0
