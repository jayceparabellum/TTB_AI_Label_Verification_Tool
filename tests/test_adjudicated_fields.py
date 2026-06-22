"""Expanded adjudicated fields: net contents + class/type (single-label path).

Both are OPTIONAL — adjudicated only when a claimed value is supplied — and use a
safe three-way verdict (PASS / FLAG / defer-to-NEEDS-REVIEW) so a new field can
never produce a confident-wrong result.
"""

from fastapi.testclient import TestClient

from app.main import app
from app.matching import match_class_type, match_net_contents
from app.reference import OFFICIAL_GOVERNMENT_WARNING
from app.verify import reverify_text, verify_fields

client = TestClient(app)

LABEL = ("Stone's Throw\nCabernet Sauvignon\nALC 5.0% BY VOL\n750 mL\n"
         + OFFICIAL_GOVERNMENT_WARNING)


# --- net contents ------------------------------------------------------------

def test_net_contents_pass():
    assert match_net_contents("750 mL", LABEL).passed


def test_net_contents_unit_conversion_pass():
    r = match_net_contents("0.75 L", LABEL)        # 0.75 L == 750 mL
    assert r.passed


def test_net_contents_flag_on_genuine_difference():
    r = match_net_contents("375 mL", LABEL)
    assert not r.passed and not r.inconclusive      # present but different -> FLAG


def test_net_contents_defers_when_absent():
    r = match_net_contents("750 mL", "Stone's Throw\nALC 5.0% BY VOL")
    assert not r.passed and r.inconclusive          # not found -> NEEDS REVIEW, not FLAG


def test_net_contents_unparseable_claim():
    r = match_net_contents("a bottle", LABEL)
    assert not r.passed and "not understood" in r.found


# --- class / type ------------------------------------------------------------

def test_class_type_pass():
    assert match_class_type("Cabernet Sauvignon", LABEL).passed


def test_class_type_flag_when_designation_differs():
    r = match_class_type("Cabernet Sauvignon Reserve", LABEL)
    assert not r.passed and not r.inconclusive      # present-but-wrong band -> FLAG


def test_class_type_defers_when_absent():
    r = match_class_type("Chardonnay", LABEL)
    assert not r.passed and r.inconclusive          # below floor -> NEEDS REVIEW


# --- only adjudicated when claimed -------------------------------------------

def test_optional_fields_skipped_when_blank():
    fields = verify_fields(LABEL, "Stone's Throw", "5.0")
    assert [f.field for f in fields] == ["brand", "alcohol_content", "government_warning"]


def test_optional_fields_adjudicated_when_supplied():
    fields = verify_fields(LABEL, "Stone's Throw", "5.0",
                           net_contents="750 mL", class_type="Cabernet Sauvignon")
    assert [f.field for f in fields][-2:] == ["net_contents", "class_type"]
    assert all(f.passed for f in fields)


def test_net_mismatch_fails_overall_verdict():
    result = reverify_text(LABEL, "Stone's Throw", "5.0", net_contents="375 mL")
    assert not result.overall_pass
    assert any(f.field == "net_contents" and not f.passed for f in result.fields)


def test_class_defer_triggers_needs_review():
    result = reverify_text(LABEL, "Stone's Throw", "5.0", class_type="Chardonnay")
    assert result.needs_review                       # inconclusive field defers the result


# --- web wiring --------------------------------------------------------------

# Result-card marker (vs. the re-check form's input labels, which always exist).
_NET_CARD = 'result-name">Net contents'
_CLASS_CARD = 'result-name">Class/type'


def test_verify_text_adjudicates_optional_fields():
    r = client.post("/verify-text", data={
        "label_text": LABEL, "brand": "Stone's Throw", "alcohol_content": "5.0",
        "net_contents": "750 mL", "class_type": "Cabernet Sauvignon",
    })
    assert r.status_code == 200
    assert _NET_CARD in r.text and _CLASS_CARD in r.text       # both adjudicated


def test_verify_text_omits_optional_when_blank():
    r = client.post("/verify-text", data={
        "label_text": LABEL, "brand": "Stone's Throw", "alcohol_content": "5.0",
    })
    assert r.status_code == 200
    # No result card for an unclaimed field (the re-check form input may still exist).
    assert _NET_CARD not in r.text and _CLASS_CARD not in r.text


# --- chat-tool parity --------------------------------------------------------

def test_chat_verify_text_tool_adjudicates_optional_fields():
    from agent.tools import run_verify_text
    out = run_verify_text(LABEL, "Stone's Throw", "5.0",
                          net_contents="750 mL", class_type="Cabernet Sauvignon")
    names = [f["field"] for f in out["fields"]]
    assert "net_contents" in names and "class_type" in names
    assert out["overall_pass"]                      # both match in LABEL


def test_chat_verify_text_tool_skips_optional_when_blank():
    from agent.tools import run_verify_text
    out = run_verify_text(LABEL, "Stone's Throw", "5.0")
    assert [f["field"] for f in out["fields"]] == \
        ["brand", "alcohol_content", "government_warning"]


# --- regressions from the session quality review -----------------------------

def test_short_absent_class_designations_defer_not_flag():
    # 'Gin'/'Rum'/'Port' are real designations but absent here; they must never
    # confidently FLAG on incidental character overlap (zero-confident-wrong).
    label = "BARREL OAK\nCabernet Sauvignon\nNapa Valley\n750 mL"
    for designation in ("Gin", "Rum", "Port"):
        r = match_class_type(designation, label)
        assert r.inconclusive, designation                      # defers to REVIEW...
        assert not (not r.passed and not r.inconclusive), designation  # ...never FLAG


def test_discriminating_class_designation_still_flags_when_different():
    r = match_class_type("Cabernet Sauvignon Reserve",
                         "BARREL OAK\nCabernet Sauvignon\n750 mL")
    assert not r.passed and not r.inconclusive                  # present-but-different


def test_thousands_separator_net_contents_matches():
    for claim in ("1 L", "1000 mL", "1,000 mL"):
        assert match_net_contents(claim, "BIG BOTTLE\n1,000 mL").passed, claim


def test_eu_decimal_comma_net_contents_still_parses():
    assert match_net_contents("0.75 L", "X\n0,75 L").passed     # 0,75 L == 750 mL


# --- U3: standards-of-identity recognition wired into the verdict -------------

def _class_field(result):
    return next(f for f in result.fields if f.field == "class_type")


def test_recognized_and_present_class_type_passes():
    # "Cabernet Sauvignon" is a recognized wine class/type and is on LABEL.
    r = reverify_text(LABEL, "Stone's Throw", "5.0", class_type="Cabernet Sauvignon")
    assert _class_field(r).passed


def test_unrecognized_present_class_type_needs_review_never_pass_or_flag():
    # An unrecognized designation that IS on the label must NOT confidently PASS
    # (and never confident-FLAG) — it defers to NEEDS REVIEW.
    label = "Stone's Throw\nUnicorn Juice\nALC 5.0% BY VOL\n" + OFFICIAL_GOVERNMENT_WARNING
    r = reverify_text(label, "Stone's Throw", "5.0", class_type="Unicorn Juice")
    ct = _class_field(r)
    assert not ct.passed and ct.inconclusive            # NEEDS REVIEW, not PASS
    assert r.needs_review


def test_recognized_but_absent_class_type_defers():
    # "Bourbon" is recognized but not on this wine label → defer, not PASS.
    r = reverify_text(LABEL, "Stone's Throw", "5.0", class_type="Bourbon")
    assert not _class_field(r).passed


# --- U5: recognition citation/recommendation visible on the web surface -------

def test_web_recognized_class_type_shows_citation():
    r = client.post("/verify-text", data={
        "label_text": LABEL, "brand": "Stone's Throw", "alcohol_content": "5.0",
        "class_type": "Cabernet Sauvignon"})
    assert r.status_code == 200
    assert "27 CFR §4.21" in r.text                       # controlling citation surfaced


def test_web_unrecognized_class_type_shows_review_recommendation():
    label = "Stone's Throw\nUnicorn Juice\nALC 5.0% BY VOL\n" + OFFICIAL_GOVERNMENT_WARNING
    r = client.post("/verify-text", data={
        "label_text": label, "brand": "Stone's Throw", "alcohol_content": "5.0",
        "class_type": "Unicorn Juice"})
    assert r.status_code == 200
    assert 'result-name">Class/type' in r.text
    assert "recommend human review" in r.text             # recommendation surfaced


# --- U6: spirits coverage at the text level (image fixtures deferred) ---------

def test_recognized_spirits_class_type_passes_when_present():
    label = ("Old Reserve\nKentucky Straight Bourbon Whiskey\nALC 45% BY VOL\n"
             + OFFICIAL_GOVERNMENT_WARNING)
    r = reverify_text(label, "Old Reserve", "45", class_type="Bourbon")
    assert _class_field(r).passed                          # spirits recognized + present


# --- compositional ABV advisory surfaced in validate_class_type --------------
# ADVISORY only: an out-of-range ABV adds a REVIEW advisory with a citation but never
# turns the tool result into a rejection; in-range/absent ABV is OK or skipped.

def test_validate_class_type_in_range_abv_is_ok():
    from agent.tools import validate_class_type
    out = validate_class_type.invoke(
        {"claimed_designation": "Bourbon", "beverage_type": "spirits",
         "claimed_abv": "45"})
    assert out["advisory"] is True and out["status"] == "OK"
    assert out["composition"]["status"] == "OK"
    assert out["composition"]["citation"]["section"] == "5.143"
    assert "reject" not in str(out).lower() or "auto-rejection" in str(out).lower()


def test_validate_class_type_out_of_range_abv_adds_review_never_reject():
    from agent.tools import validate_class_type
    out = validate_class_type.invoke(
        {"claimed_designation": "Bourbon", "beverage_type": "spirits",
         "claimed_abv": "35"})           # below the 40% spirits floor
    assert out["advisory"] is True
    assert out["status"] == "REVIEW"     # escalated OK -> REVIEW
    assert out["status"] not in {"FAIL", "FLAG", "REJECT"}
    comp = out["composition"]
    assert comp["status"] == "REVIEW" and comp["advisory"] is True
    assert comp["citation"]["section"] == "5.143"
    assert "never an auto-rejection" in comp["assessment"]


def test_validate_class_type_proof_value_is_understood():
    from agent.tools import validate_class_type
    # 78 proof = 39% ABV, below the 40% whisky floor -> REVIEW.
    out = validate_class_type.invoke(
        {"claimed_designation": "Whisky", "claimed_abv": "78 proof"})
    assert out["composition"]["status"] == "REVIEW"


def test_validate_class_type_skips_composition_without_abv():
    from agent.tools import validate_class_type
    out = validate_class_type.invoke(
        {"claimed_designation": "Bourbon", "beverage_type": "spirits"})
    assert "composition" not in out      # no ABV claimed -> no-op, no flag
    assert out["advisory"] is True


def test_validate_class_type_skips_composition_for_class_without_bound():
    from agent.tools import validate_class_type
    # 'Vodka' is recognized but carries no cited ABV envelope -> skipped.
    out = validate_class_type.invoke(
        {"claimed_designation": "Vodka", "claimed_abv": "5"})
    assert "composition" not in out and out["advisory"] is True
