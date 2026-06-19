"""U1 — agent-eval case roster + snapshot schema.

The roster is the contract the record->gate harness grades against: every case
must name a real tool and a non-empty invariant set, and the roster as a whole must
cover each core flow and each invariant (PRD R5/R3). The snapshot schema must
round-trip a representative transcript without loss so committed JSON replays cleanly.
"""

from __future__ import annotations

from agent.tools import ALL_TOOLS, WRITE_TOOL_NAMES
from eval import agent_cases as AC


_TOOL_NAMES = {t.name for t in ALL_TOOLS}


def test_roster_cases_name_real_tools_and_invariants():
    assert AC.ROSTER, "roster must not be empty"
    ids = [c.id for c in AC.ROSTER]
    assert len(ids) == len(set(ids)), "case ids must be unique"
    for c in AC.ROSTER:
        assert c.expected_tool in _TOOL_NAMES, f"{c.id}: unknown tool {c.expected_tool}"
        assert c.invariants, f"{c.id}: empty invariant set"
        assert c.invariants <= AC.ALL_INVARIANTS, f"{c.id}: unknown invariant"


def test_roster_covers_every_core_flow():
    tools = {c.expected_tool for c in AC.ROSTER}
    for flow in ("verify_label", "verify_text", "batch_verify",
                 "regulatory_lookup", "explain_flag"):
        assert flow in tools, f"no case exercises {flow}"


def test_roster_covers_every_invariant():
    covered = set().union(*(c.invariants for c in AC.ROSTER))
    assert covered == AC.ALL_INVARIANTS, f"missing invariant coverage: {AC.ALL_INVARIANTS - covered}"


def test_roster_has_pass_and_flag_verify_label_cases():
    vl = [c for c in AC.ROSTER if c.expected_tool == "verify_label"]
    assert len(vl) >= 2, "need a PASS and a FLAG verify_label case"
    images = {c.active_image_id for c in vl}
    assert "clean_pass" in images and "abv_mismatch" in images


def test_write_case_is_a_real_write_tool_and_gated():
    writes = [c for c in AC.ROSTER if c.is_write]
    assert writes, "need at least one WRITE (confirm-gate) case"
    for c in writes:
        assert c.expected_tool in WRITE_TOOL_NAMES
        assert AC.INV_CONFIRM_GATE in c.invariants


def test_out_of_corpus_case_present_for_refusal():
    refused = [c for c in AC.ROSTER if c.id == "regulatory_lookup_refused"]
    assert refused, "need an out-of-corpus -> refused case"
    assert AC.INV_CITE_OR_REFUSE in refused[0].invariants


def test_snapshot_round_trips_a_representative_transcript(tmp_path):
    snap = AC.Snapshot(
        case_id="verify_label_flag",
        expected_tool="verify_label",
        invariants=[AC.INV_VERDICT_VERBATIM, AC.INV_TOOL_ROUTING],
        is_write=False,
        inputs={"kind": "image", "image_id": "abv_mismatch",
                "brand": "Stone's Throw", "alcohol_content": "5.0"},
        transcript=[
            AC.tool_call_step("verify_label", {"brand": "Stone's Throw",
                                               "alcohol_content": "5.0"}),
            AC.tool_result_step("verify_label", {"overall_pass": False,
                                                 "needs_review": False}),
            AC.message_step("The label FLAGs on alcohol content."),
        ],
        ground_truth={"overall_pass": False, "needs_review": False},
        judge={"faithfulness": 5, "clarity": 4, "justification": "matches the tool"},
    )
    path = AC.dump(snap, tmp_path / "verify_label_flag.json")
    back = AC.load(path)
    assert back.to_dict() == snap.to_dict()


def test_load_all_reads_directory_sorted(tmp_path):
    for cid in ("b_case", "a_case"):
        AC.dump(AC.Snapshot(case_id=cid, expected_tool="verify_label",
                            invariants=[], is_write=False), tmp_path / f"{cid}.json")
    loaded = AC.load_all(tmp_path)
    assert [s.case_id for s in loaded] == ["a_case", "b_case"]


def test_load_all_on_empty_dir_returns_nothing(tmp_path):
    assert AC.load_all(tmp_path / "nope") == []
