"""U4 — verify_text tool. The pasted label TEXT is verified through the SAME
deterministic core (reverify_text) the /verify-text page uses, serialized exactly
like verify_label. The tool never emits a verdict of its own; parity is the point.
Pure text -> no image fixtures, so no sample-image skip guard is needed."""

from app.reference import OFFICIAL_GOVERNMENT_WARNING
from app.verify import reverify_text
from agent import tools as T

# A complete, compliant label as text: brand, ABV, and the exact warning wording.
PASS_TEXT = (
    "Cedar Hollow\nCraft Lager\nALC 5.0% BY VOL\n12 FL OZ\n"
    + OFFICIAL_GOVERNMENT_WARNING
)


def test_verify_text_is_a_read_tool_in_the_roster():
    assert "verify_text" in {t.name for t in T.READ_TOOLS}
    assert "verify_text" not in T.WRITE_TOOL_NAMES   # READ -> never confirm-gated


def test_parity_with_core_reverify_text_on_a_pass():
    out = T.verify_text.invoke(
        {"label_text": PASS_TEXT, "brand": "Cedar Hollow", "alcohol_content": "5.0"})
    core = reverify_text(PASS_TEXT, brand="Cedar Hollow", alcohol_content="5.0")
    assert out["overall_pass"] is core.overall_pass is True
    # Field-level verdicts match the core verbatim.
    assert {f["field"]: f["passed"] for f in out["fields"]} == \
        {f.field: f.passed for f in core.fields}


def test_flag_case_matches_core_when_abv_is_wrong():
    # Claimed ABV (9.9) contradicts the text (5.0) -> the core FLAGS; the tool must
    # report the same FLAG, never soften it.
    out = T.verify_text.invoke(
        {"label_text": PASS_TEXT, "brand": "Cedar Hollow", "alcohol_content": "9.9"})
    core = reverify_text(PASS_TEXT, brand="Cedar Hollow", alcohol_content="9.9")
    assert out["overall_pass"] is core.overall_pass is False
    assert {f["field"]: f["passed"] for f in out["fields"]}["alcohol_content"] is False


def test_unreadable_text_is_a_friendly_message_not_a_verdict():
    out = T.verify_text.invoke(
        {"label_text": "  ", "brand": "Cedar Hollow", "alcohol_content": "5.0"})
    assert "error" in out                      # guarded before the core runs
    assert "overall_pass" not in out           # never fabricates a pass/fail


def test_run_verify_text_helper_serializes_identically_to_the_tool():
    # The helper is what tests/parity assertions call without InjectedState plumbing.
    helper = T.run_verify_text(PASS_TEXT, "Cedar Hollow", "5.0")
    assert set(helper) >= {"readable", "overall_pass", "needs_review",
                           "confidence", "elapsed_ms", "fields", "message"}
