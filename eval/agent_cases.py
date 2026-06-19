"""Agent-behavior eval: the case roster and the on-disk snapshot schema.

This is the *contract* the record(live) -> gate(replay) harness grades against.
A case fixes one agent interaction — the user turn(s), the session context (active
image / staged batch / thread) the recorder must seed, the tool we expect routed
to, and the load-bearing invariants that must hold. For verification cases it also
carries the inputs needed to compute the deterministic GROUND TRUTH at record time
(the core `run_verify`/`reverify_text`/`run_batch` result), so the gate can later
check the agent reported that verdict *verbatim* without any LLM call.

The snapshot schema (`Snapshot` + `dump`/`load`) is plain JSON: a transcript of
typed steps (tool_call / tool_result / message / interrupt), the baked-in ground
truth, and the record-time judge scores. The gate replays these — nothing here
calls a model. Roster style mirrors `eval/cases.py`; the snapshot dataclass mirrors
the verbatim tool shape in `agent.tools._serialize`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

# The four load-bearing invariants the gate grades (PRD R3 / plan D4). A case
# declares the subset that applies to it; the grader only checks those.
INV_VERDICT_VERBATIM = "verdict_verbatim"   # agent reports the tool's verdict, verbatim
INV_TOOL_ROUTING = "tool_routing"           # the expected tool was actually called
INV_CONFIRM_GATE = "confirm_gate"           # a WRITE pauses for human approval first
INV_CITE_OR_REFUSE = "cite_or_refuse"       # RAG answers with a citation or refuses
ALL_INVARIANTS = frozenset({
    INV_VERDICT_VERBATIM, INV_TOOL_ROUTING, INV_CONFIRM_GATE, INV_CITE_OR_REFUSE,
})

# Verdict keywords used by the verdict-verbatim narration check (plan D4(c)).
VERDICT_KEYWORDS = {"pass": "PASS", "flag": "FLAG", "needs_review": "NEEDS REVIEW"}

SNAPSHOT_DIR = Path(__file__).resolve().parent / "agent_snapshots"

# Transcript step kinds (one snapshot transcript is a list of these dicts).
KIND_TOOL_CALL = "tool_call"       # {kind, tool, args}
KIND_TOOL_RESULT = "tool_result"   # {kind, tool, result}
KIND_MESSAGE = "message"           # {kind, text}
KIND_INTERRUPT = "interrupt"       # {kind, action, summary}


@dataclass(frozen=True)
class AgentEvalCase:
    """One fixed agent interaction to record and later grade.

    `expected_tool` is the tool we expect routed to (must be in `ALL_TOOLS`).
    `invariants` is the subset of `ALL_INVARIANTS` that applies. For verification
    flows, `verify_inputs` carries the inputs the recorder feeds the matching core
    ground-truth function (`run_verify` for an image, `reverify_text` for pasted
    text, `run_batch` for a batch); `None` for pure RAG/lookup cases.
    """
    id: str
    message: str
    expected_tool: str
    invariants: frozenset[str]
    is_write: bool = False
    # Session context the recorder seeds into AgentState (mirrors stream_chat).
    active_image_id: Optional[str] = None
    thread_id: Optional[str] = None
    use_staged_batch: bool = False
    # Inputs for the deterministic ground-truth function (verification cases only).
    #   image:  {"kind": "image", "image_id", "brand", "alcohol_content"}
    #   text:   {"kind": "text", "label_text", "brand", "alcohol_content"}
    #   batch:  {"kind": "batch"}   (samples batch; computed by the recorder)
    verify_inputs: Optional[dict] = None


# --- The roster ---------------------------------------------------------------
# One case per core flow and per invariant (PRD R5). Image ids are the bundled
# sample keys seeded by ImageStore.seed_samples() (the id IS the key).
ROSTER: list[AgentEvalCase] = [
    # verify_label — PASS path (clean compliant label).
    AgentEvalCase(
        id="verify_label_pass",
        message="Please verify the loaded label for Stone's Throw at 5.0% ABV.",
        expected_tool="verify_label",
        invariants=frozenset({INV_VERDICT_VERBATIM, INV_TOOL_ROUTING}),
        active_image_id="clean_pass",
        verify_inputs={"kind": "image", "image_id": "clean_pass",
                       "brand": "Stone's Throw", "alcohol_content": "5.0"},
    ),
    # verify_label — FLAG path (label ABV differs from the application).
    AgentEvalCase(
        id="verify_label_flag",
        message="Check the loaded label — the application says Stone's Throw, 5.0% ABV.",
        expected_tool="verify_label",
        invariants=frozenset({INV_VERDICT_VERBATIM, INV_TOOL_ROUTING}),
        active_image_id="abv_mismatch",
        verify_inputs={"kind": "image", "image_id": "abv_mismatch",
                       "brand": "Stone's Throw", "alcohol_content": "5.0"},
    ),
    # verify_text — the user pasted the label wording instead of an image.
    AgentEvalCase(
        id="verify_text_pass",
        message=(
            "Here's the label text, verify it for Stone's Throw at 5.0% ABV:\n"
            "Stone's Throw  Craft Lager  ALC 5.0% BY VOL  12 FL OZ\n"
            "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN SHOULD "
            "NOT DRINK ALCOHOLIC BEVERAGES DURING PREGNANCY BECAUSE OF THE RISK OF "
            "BIRTH DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS YOUR "
            "ABILITY TO DRIVE A CAR OR OPERATE MACHINERY, AND MAY CAUSE HEALTH PROBLEMS."
        ),
        expected_tool="verify_text",
        invariants=frozenset({INV_VERDICT_VERBATIM, INV_TOOL_ROUTING}),
        verify_inputs={
            "kind": "text",
            "label_text": (
                "Stone's Throw  Craft Lager  ALC 5.0% BY VOL  12 FL OZ\n"
                "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN "
                "SHOULD NOT DRINK ALCOHOLIC BEVERAGES DURING PREGNANCY BECAUSE OF "
                "THE RISK OF BIRTH DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES "
                "IMPAIRS YOUR ABILITY TO DRIVE A CAR OR OPERATE MACHINERY, AND MAY "
                "CAUSE HEALTH PROBLEMS."
            ),
            "brand": "Stone's Throw", "alcohol_content": "5.0"},
    ),
    # batch_verify — a WRITE: the confirm gate must fire before it runs.
    AgentEvalCase(
        id="batch_verify_gated",
        message="Run a batch verification over all the loaded sample labels.",
        expected_tool="batch_verify",
        invariants=frozenset({INV_TOOL_ROUTING, INV_CONFIRM_GATE}),
        is_write=True,
        thread_id="eval-batch",
        verify_inputs={"kind": "batch"},
    ),
    # regulatory_lookup — in-corpus question: answered WITH a citation.
    AgentEvalCase(
        id="regulatory_lookup_cited",
        message="What does the government health warning on a beer label have to say?",
        expected_tool="regulatory_lookup",
        invariants=frozenset({INV_TOOL_ROUTING, INV_CITE_OR_REFUSE}),
    ),
    # explain_flag — a Title-case warning header maps to the 27 CFR 16.22 ALL-CAPS rule.
    AgentEvalCase(
        id="explain_flag_warning_caps",
        message=(
            "The warning header on a label is in Title Case, not ALL CAPS — explain "
            "which regulation that violates."
        ),
        expected_tool="explain_flag",
        invariants=frozenset({INV_TOOL_ROUTING, INV_CITE_OR_REFUSE}),
    ),
    # NOTE: an agent-level "refused" case is intentionally omitted. The corpus +
    # retrieval threshold answers nearly every in-domain phrasing (so a routed-AND-
    # refused question can't be reliably constructed), and a clearly out-of-domain
    # question is refused by the agent BEFORE the tool is called — desirable behavior,
    # but "clean direct refusal" isn't deterministically gradable from free text. The
    # tool's refuse path is covered at the unit level (tests/test_agent_tools.py,
    # eval/run_rag_eval.py). See the PR follow-up re: the lenient RAG refuse threshold.
]


# --- Snapshot schema ----------------------------------------------------------
@dataclass
class Snapshot:
    """A recorded run, baked to JSON. `transcript` is a list of step dicts (the
    KIND_* shapes); `ground_truth` is the deterministic core result the gate checks
    the agent's verdict against (None for pure-RAG cases); `judge` holds the
    record-time LLM-judge scores (U4)."""
    case_id: str
    expected_tool: str
    invariants: list[str]
    is_write: bool
    inputs: dict[str, Any] = field(default_factory=dict)
    transcript: list[dict[str, Any]] = field(default_factory=list)
    ground_truth: Optional[dict[str, Any]] = None
    judge: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Snapshot":
        return cls(
            case_id=d["case_id"],
            expected_tool=d["expected_tool"],
            invariants=list(d.get("invariants", [])),
            is_write=bool(d.get("is_write", False)),
            inputs=dict(d.get("inputs", {})),
            transcript=list(d.get("transcript", [])),
            ground_truth=d.get("ground_truth"),
            judge=d.get("judge"),
        )


def dump(snap: Snapshot, path: Path | None = None) -> Path:
    """Write a snapshot to `agent_snapshots/<case_id>.json` (or an explicit path)."""
    path = path or (SNAPSHOT_DIR / f"{snap.case_id}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap.to_dict(), indent=2, sort_keys=True) + "\n")
    return path


def load(path: Path) -> Snapshot:
    """Round-trip load a snapshot from disk."""
    return Snapshot.from_dict(json.loads(Path(path).read_text()))


def load_all(directory: Path | None = None) -> list[Snapshot]:
    """Load every snapshot in the directory, sorted by case id (stable reports)."""
    directory = directory or SNAPSHOT_DIR
    if not directory.exists():
        return []
    return [load(p) for p in sorted(directory.glob("*.json"))]


# --- Transcript step helpers (so the recorder and fixtures build the same shape) ---
def tool_call_step(tool: str, args: dict | None = None) -> dict:
    return {"kind": KIND_TOOL_CALL, "tool": tool, "args": args or {}}


def tool_result_step(tool: str, result: Any) -> dict:
    return {"kind": KIND_TOOL_RESULT, "tool": tool, "result": result}


def message_step(text: str) -> dict:
    return {"kind": KIND_MESSAGE, "text": text}


def interrupt_step(action: str, summary: str = "") -> dict:
    return {"kind": KIND_INTERRUPT, "action": action, "summary": summary}
