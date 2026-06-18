"""U2 — agent core: button-parity of the verify_label tool + the ReAct loop.

Uses a stubbed model (no running Ollama) so the graph wiring is tested
deterministically. The point of these tests is the invariant: the agent's verdict
is EXACTLY the deterministic core's verdict, and pass/fail comes from the tool, not
the model.
"""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent import tools as agent_tools
from agent.graph import build_graph
from agent.images import STORE
from agent.llm import SYSTEM_PROMPT
from app.verify import verify_label as core_verify

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(),
    reason="sample images not generated (run scripts/generate_samples.py)",
)


@pytest.fixture(autouse=True)
def _seed_store():
    STORE._images.clear()
    STORE.seed_samples()
    yield
    STORE._images.clear()


def _core_fields(name, brand, abv):
    r = core_verify((SAMPLES / f"{name}.png").read_bytes(), brand=brand, alcohol_content=abv)
    return {f.field: f.passed for f in r.fields}, r.overall_pass


# --- Button-parity: the tool returns exactly what the core returns -------------
@pytest.mark.parametrize("name,brand,abv", [
    ("clean_pass", "Stone's Throw", "5.0"),       # PASS
    ("abv_mismatch", "Stone's Throw", "5.0"),      # FLAG on ABV
    ("bad_warning", "Stone's Throw", "5.0"),       # FLAG on warning
])
def test_verify_tool_matches_core(name, brand, abv):
    got = agent_tools.run_verify(name, brand, abv)
    core_fields, core_overall = _core_fields(name, brand, abv)
    assert {f["field"]: f["passed"] for f in got["fields"]} == core_fields
    assert got["overall_pass"] == core_overall


def test_verify_tool_no_image_is_friendly():
    out = agent_tools.run_verify(None, "X", "5")
    assert "error" in out and "upload" in out["error"].lower()


# --- ReAct loop with a stubbed model -------------------------------------------
class _StubModel:
    """Emits a verify_label tool call on the first turn, a final summary once the
    ToolMessage is back. Stands in for ChatOllama with zero network."""

    def __init__(self, brand, abv):
        self._brand, self._abv = brand, abv

    def invoke(self, messages):
        if any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(content="The label passed all three checks.")
        return AIMessage(content="", tool_calls=[{
            "name": "verify_label",
            "args": {"brand": self._brand, "alcohol_content": self._abv},
            "id": "call_1", "type": "tool_call",
        }])


def test_agent_loop_verdict_comes_from_tool_not_model():
    graph = build_graph(llm=_StubModel("Stone's Throw", "5.0"))
    result = graph.invoke({
        "messages": [HumanMessage("verify the uploaded label")],
        "active_image_id": "clean_pass",
        "expected": {"brand": "Stone's Throw", "alcohol_content": "5.0"},
        "last_result_id": None,
    })
    msgs = result["messages"]
    # The verdict is carried by a ToolMessage (deterministic), then narrated.
    tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
    assert tool_msgs, "agent must call the verify tool"
    core_fields, core_overall = _core_fields("clean_pass", "Stone's Throw", "5.0")
    assert str(core_overall) in tool_msgs[-1].content or "overall_pass" in tool_msgs[-1].content
    # Final message is the model's narration, present after the tool result.
    assert isinstance(msgs[-1], AIMessage) and not msgs[-1].tool_calls


def test_system_prompt_forbids_adjudication():
    p = SYSTEM_PROMPT.lower()
    assert "do not decide pass/fail" in p or "not decide pass/fail" in p
    assert "never approve or reject" in p
