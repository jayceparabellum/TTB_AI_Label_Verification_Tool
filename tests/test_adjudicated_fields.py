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
