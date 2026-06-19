"""Agent-behavior eval harness: record(live) -> gate(replay).

Two modes, mirroring the `eval-record` / `eval-gate` split:

  * `record`  drives the agent LIVE (cloud Claude) over the case roster, captures
              each run's transcript + confirm-gate interrupts, computes the
              deterministic ground truth, scores explanations with the LLM-judge,
              and writes a JSON snapshot per case. SPENDS CREDITS — manual, infrequent.
  * `gate`    REPLAYS the committed snapshots and grades the load-bearing invariants
              deterministically (verdict-verbatim, tool routing, confirm-gate fires
              on a WRITE, RAG cite-or-refuse) plus the baked-in judge thresholds.
              No LLM, no credits — the CI-safe path. Non-zero exit on any failure.

The grader is the core value and is fully offline: it reads only the snapshot JSON
and re-derives nothing from a model. Recording is a documented manual step (see the
README + `record` below); the gate must work on whatever snapshots exist.

Usage:
  python eval/run_agent_eval.py gate              # replay + grade + write AGENT_REPORT.md
  LLM_BACKEND=anthropic python eval/run_agent_eval.py record   # live refresh (credits)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval import agent_cases as AC                              # noqa: E402
from eval.agent_cases import (                                  # noqa: E402
    INV_CITE_OR_REFUSE, INV_CONFIRM_GATE, INV_TOOL_ROUTING, INV_VERDICT_VERBATIM,
    KIND_INTERRUPT, KIND_MESSAGE, KIND_TOOL_CALL, KIND_TOOL_RESULT, Snapshot,
    VERDICT_KEYWORDS,
)

# The verification tools whose result feeds the verdict-verbatim check.
_VERIFY_TOOLS = {"verify_label", "verify_text", "batch_verify"}
# Default judge threshold (1–5 scale); each rubric dimension must clear it (U4).
JUDGE_THRESHOLD = 3


# --- Transcript readers -------------------------------------------------------
def _steps(snap: Snapshot, kind: str) -> list[dict]:
    return [s for s in snap.transcript if s.get("kind") == kind]


def _called_tools(snap: Snapshot) -> list[str]:
    return [s.get("tool") for s in _steps(snap, KIND_TOOL_CALL)]


def _final_message(snap: Snapshot) -> str:
    msgs = _steps(snap, KIND_MESSAGE)
    return (msgs[-1].get("text") or "") if msgs else ""


def _verify_result(snap: Snapshot) -> dict | None:
    """The result of the first verification tool that ran (None if none did)."""
    for s in _steps(snap, KIND_TOOL_RESULT):
        if s.get("tool") in _VERIFY_TOOLS:
            return s.get("result")
    return None


def _verdict_projection(result: dict) -> dict:
    """The verdict-bearing core of a verification result, stripped of fields that
    don't change the verdict: wall-clock timing (`elapsed_ms`, varies run-to-run)
    and the advisory `regulation` annotation the agent tool attaches to FLAGGED
    fields (a grounded citation that never alters pass/fail — see
    agent.tools._attach_regulations). What remains — overall_pass, needs_review,
    readable, and each field's passed/expected/found — IS the verdict the agent
    must report verbatim."""
    out = {k: v for k, v in result.items() if k not in {"elapsed_ms"}}
    fields = out.get("fields")
    if isinstance(fields, list):
        out["fields"] = [{k: v for k, v in f.items() if k != "regulation"}
                         if isinstance(f, dict) else f for f in fields]
    return out


def _verdict_eq(result, ground_truth) -> bool:
    """True when a tool result carries the same verdict as the ground truth — i.e.
    the agent's tool reported it verbatim (timing + advisory annotations aside)."""
    if not isinstance(result, dict) or not isinstance(ground_truth, dict):
        return result == ground_truth
    return _verdict_projection(result) == _verdict_projection(ground_truth)


def _verdict_word(result: dict | None) -> str | None:
    """Map a serialized verification result to its verdict keyword (D4(c))."""
    if not isinstance(result, dict) or "overall_pass" not in result:
        return None
    if result.get("overall_pass"):
        return VERDICT_KEYWORDS["pass"]
    if result.get("needs_review"):
        return VERDICT_KEYWORDS["needs_review"]
    return VERDICT_KEYWORDS["flag"]


# --- The four invariant graders (each returns (passed, detail)) ---------------
def _grade_tool_routing(snap: Snapshot) -> tuple[bool, str]:
    called = _called_tools(snap)
    ok = snap.expected_tool in called
    return ok, (f"called {snap.expected_tool}" if ok
                else f"expected {snap.expected_tool}, called {called or 'nothing'}")


def _grade_verdict_verbatim(snap: Snapshot) -> tuple[bool, str]:
    """D4: (a) a verification tool ran, (b) its result == ground_truth, (c) the
    final message contains the matching verdict keyword and no contradicting one."""
    result = _verify_result(snap)
    if result is None:
        return False, "no verification tool result in transcript"
    if snap.ground_truth is not None and not _verdict_eq(result, snap.ground_truth):
        return False, "tool result does not match deterministic ground truth"
    want = _verdict_word(result)
    if want is None:
        return False, "verification result has no verdict (error/unreadable)"
    msg = _final_message(snap).upper()
    if want not in msg:
        return False, f"final message is missing the verdict keyword {want!r}"
    contradicting = [w for w in VERDICT_KEYWORDS.values() if w != want and w in msg]
    if contradicting:
        return False, f"final message contradicts the verdict with {contradicting}"
    return True, f"reported {want} verbatim"


def _grade_confirm_gate(snap: Snapshot) -> tuple[bool, str]:
    """A WRITE must pause: an interrupt step must precede the write tool's result."""
    interrupt_idx = next(
        (i for i, s in enumerate(snap.transcript) if s.get("kind") == KIND_INTERRUPT),
        None)
    result_idx = next(
        (i for i, s in enumerate(snap.transcript)
         if s.get("kind") == KIND_TOOL_RESULT and s.get("tool") == snap.expected_tool),
        None)
    if interrupt_idx is None:
        return False, "WRITE ran with no confirm-gate interrupt"
    if result_idx is not None and interrupt_idx > result_idx:
        return False, "confirm-gate fired AFTER the write executed"
    return True, "confirm gate fired before the write"


def _grade_cite_or_refuse(snap: Snapshot) -> tuple[bool, str]:
    """Every RAG tool result must be answered+citation or refused+no-citation."""
    rag_results = [s.get("result") for s in _steps(snap, KIND_TOOL_RESULT)
                   if isinstance(s.get("result"), dict) and "status" in s["result"]]
    if not rag_results:
        return False, "no RAG tool result in transcript"
    for r in rag_results:
        cites = r.get("citations") or []
        if r.get("status") == "answered" and not cites:
            return False, "answered with no citation"
        if r.get("status") == "refused" and cites:
            return False, "refused but carried a citation"
        if r.get("status") not in {"answered", "refused"}:
            return False, f"unexpected RAG status {r.get('status')!r}"
    return True, "answered-with-cite or refused"


_GRADERS = {
    INV_TOOL_ROUTING: _grade_tool_routing,
    INV_VERDICT_VERBATIM: _grade_verdict_verbatim,
    INV_CONFIRM_GATE: _grade_confirm_gate,
    INV_CITE_OR_REFUSE: _grade_cite_or_refuse,
}


def _grade_judge(snap: Snapshot, threshold: int = JUDGE_THRESHOLD) -> tuple[bool, str] | None:
    """Threshold-check the baked-in judge scores. NO model call (D3). Returns None
    when the case carries no judge block (judge is optional, U4 scaffold)."""
    judge = snap.judge
    if not judge:
        return None
    dims = {k: v for k, v in judge.items() if isinstance(v, (int, float))}
    if not dims:
        return None
    below = {k: v for k, v in dims.items() if v < threshold}
    if below:
        return False, f"judge below threshold {threshold}: {below}"
    return True, f"judge >= {threshold}: {dims}"


def grade_snapshot(snap: Snapshot, judge_threshold: int = JUDGE_THRESHOLD) -> dict:
    """Grade one snapshot's declared invariants + optional judge thresholds.
    Returns {case_id, invariants:{name:(passed, detail)}, judge, passed}."""
    results: dict[str, tuple[bool, str]] = {}
    for inv in snap.invariants:
        grader = _GRADERS.get(inv)
        if grader is None:
            results[inv] = (False, f"no grader for invariant {inv!r}")
        else:
            results[inv] = grader(snap)
    judge = _grade_judge(snap, judge_threshold)
    passed = all(ok for ok, _ in results.values()) and (judge is None or judge[0])
    return {"case_id": snap.case_id, "invariants": results, "judge": judge,
            "passed": passed}


def grade_all(snapshots: list[Snapshot], judge_threshold: int = JUDGE_THRESHOLD) -> list[dict]:
    return [grade_snapshot(s, judge_threshold) for s in snapshots]


# --- Report (U5) --------------------------------------------------------------
_INV_COLS = [INV_VERDICT_VERBATIM, INV_TOOL_ROUTING, INV_CONFIRM_GATE, INV_CITE_OR_REFUSE]
_INV_HEAD = {INV_VERDICT_VERBATIM: "verbatim", INV_TOOL_ROUTING: "routing",
             INV_CONFIRM_GATE: "confirm-gate", INV_CITE_OR_REFUSE: "cite/refuse"}


def _cell(grades: dict, inv: str) -> str:
    if inv not in grades["invariants"]:
        return "—"
    ok, _detail = grades["invariants"][inv]
    return "✅" if ok else "❌"


def render_report(graded: list[dict]) -> str:
    n = len(graded)
    passed = sum(g["passed"] for g in graded)
    lines = [
        "# Agent Behavior Eval Report", "",
        "Replays the committed agent snapshots and grades the load-bearing "
        "invariants **deterministically** (no LLM, no credits): the agent reports "
        "the deterministic tool's verdict **verbatim**, routes to the right tool, "
        "never runs a WRITE without the confirm gate firing, and RAG **cites-or-"
        "refuses**. Judge scores are baked in at record time and threshold-checked "
        "here. `record` (live, spends credits) refreshes the snapshots; this `gate` "
        "is the free, CI-safe path.", "",
    ]
    if n == 0:
        lines += [
            "_No snapshots recorded yet._ Run "
            "`LLM_BACKEND=anthropic python eval/run_agent_eval.py record` to capture "
            "them (spends Anthropic credits), commit `eval/agent_snapshots/*.json`, "
            "then re-run the gate.", "",
        ]
        return "\n".join(lines) + "\n"
    header = "| case | " + " | ".join(_INV_HEAD[i] for i in _INV_COLS) + " | judge | result |"
    sep = "|------|" + "|".join(["------"] * (len(_INV_COLS) + 2)) + "|"
    lines += [header, sep]
    for g in graded:
        cells = " | ".join(_cell(g, i) for i in _INV_COLS)
        if g["judge"] is None:
            judge = "—"
        else:
            judge = "✅" if g["judge"][0] else "❌"
        result = "✅ PASS" if g["passed"] else "❌ FAIL"
        lines.append(f"| {g['case_id']} | {cells} | {judge} | {result} |")
    lines += ["", f"- **Cases passing:** {passed}/{n} = "
              f"**{100.0 * passed / n:.1f}%** → "
              f"{'**PASS** (all invariants hold)' if passed == n else '**FAIL**'}"]
    fails = [g for g in graded if not g["passed"]]
    if fails:
        lines += ["", "## Failures", ""]
        for g in fails:
            for inv, (ok, detail) in g["invariants"].items():
                if not ok:
                    lines.append(f"- `{g['case_id']}` — **{inv}**: {detail}")
            if g["judge"] is not None and not g["judge"][0]:
                lines.append(f"- `{g['case_id']}` — **judge**: {g['judge'][1]}")
    return "\n".join(lines) + "\n"


def run_gate(snapshot_dir: Path | None = None, judge_threshold: int = JUDGE_THRESHOLD,
             report_path: Path | None = None, write_report: bool = True) -> int:
    """Replay + grade + (optionally) write the report. Returns a process exit code
    (0 = all pass; 1 = any failure)."""
    snaps = AC.load_all(snapshot_dir)
    graded = grade_all(snaps, judge_threshold)
    report = render_report(graded)
    if write_report:
        path = report_path or (Path(__file__).resolve().parent / "AGENT_REPORT.md")
        path.write_text(report)
    print(report)
    failed = [g["case_id"] for g in graded if not g["passed"]]
    if not snaps:
        print("No snapshots to grade — record some first (see README).", file=sys.stderr)
        return 0
    if failed:
        print(f"GATE FAILED: {len(failed)} case(s) failed: {', '.join(failed)}",
              file=sys.stderr)
        return 1
    print(f"GATE PASSED: {len(snaps)} case(s) all green.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode")
    g = sub.add_parser("gate", help="replay snapshots + grade invariants (free, CI-safe)")
    g.add_argument("--snapshots", type=Path, default=None,
                   help="snapshot dir (default eval/agent_snapshots)")
    g.add_argument("--judge-threshold", type=int, default=JUDGE_THRESHOLD)
    r = sub.add_parser("record", help="drive the agent LIVE + write snapshots (SPENDS CREDITS)")
    r.add_argument("--snapshots", type=Path, default=None)
    r.add_argument("--case", action="append", default=None,
                   help="record only these case id(s); repeatable")
    r.add_argument("--no-judge", action="store_true", help="skip the record-time LLM-judge")
    args = parser.parse_args(argv)

    if args.mode == "record":
        from eval.agent_record import run_record
        return run_record(snapshot_dir=args.snapshots, only=args.case,
                          run_judge=not args.no_judge)
    # Default to the gate (the free path) when no subcommand is given.
    return run_gate(snapshot_dir=getattr(args, "snapshots", None),
                    judge_threshold=getattr(args, "judge_threshold", JUDGE_THRESHOLD))


if __name__ == "__main__":
    raise SystemExit(main())
