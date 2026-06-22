"""U2 — standards-of-identity recognition (app/standards.py).

Whole-token containment, never naive substring, fully offline. The false-positive
guard is load-bearing: a wrong recognition would wrongly PASS an invalid designation
(a confident-wrong verdict).
"""

import socket

import pytest

from app.standards import check_composition, recognize


# --- recognized (exact + alias) ----------------------------------------------

@pytest.mark.parametrize("claim,bev", [
    ("Bourbon", "spirits"),
    ("bourbon whiskey", "spirits"),
    ("Cabernet Sauvignon", "wine"),
    ("Table Wine", "wine"),
    ("LONDON DRY GIN", "spirits"),
    ("Blanco Tequila", "spirits"),
])
def test_recognized_designations(claim, bev):
    r = recognize(claim)
    assert r.recognized and r.beverage_type == bev
    assert r.citation and r.citation["section"] and r.citation["source_url"].startswith("https://")


# --- recognized within a full claimed designation (containment) --------------

@pytest.mark.parametrize("claim,section", [
    ("Kentucky Straight Bourbon Whiskey", "5.143"),
    ("Napa Valley Cabernet Sauvignon", "4.21"),
    ("Extra Añejo Tequila", "5.148"),
])
def test_recognized_within_full_designation(claim, section):
    r = recognize(claim)
    assert r.recognized and r.citation["section"] == section


# --- word-boundary false-positive guard (the load-bearing case) --------------

@pytest.mark.parametrize("claim", [
    "Virginia Dare",            # 'gin' must NOT match inside 'virginia'
    "Ginger Ale",               # 'gin' must NOT match inside 'ginger'
    "Imported Sport Drink",     # 'port'/'rum' must NOT match inside 'imported'/'sport'
])
def test_short_designation_no_incidental_match(claim):
    # Naive substring would falsely recognize these; whole-token matching must not.
    assert not recognize(claim).recognized


def test_unrecognized_designations():
    for claim in ("Unicorn Tears", "Hard Kombucha", "Sparkling Unicorn Juice"):
        r = recognize(claim)
        assert not r.recognized and r.citation is None


# --- beverage-type override + ambiguity --------------------------------------

def test_beverage_type_override_filters():
    assert recognize("Cabernet Sauvignon", beverage_type="wine").recognized
    assert not recognize("Cabernet Sauvignon", beverage_type="spirits").recognized


# --- offline -----------------------------------------------------------------

def test_recognize_runs_offline(monkeypatch):
    real = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise OSError(f"offline test: blocked outbound to {host!r}")
        return real(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    assert recognize("Bourbon").recognized


# --- compositional ABV/proof advisory (check_composition) --------------------
# Advisory only: in-range -> OK; out-of-range -> REVIEW (NEVER a confident reject);
# no rule / no ABV / unrecognized -> silent no-op. Citation present when checked.

@pytest.mark.parametrize("claim,abv,section", [
    ("Bourbon", 45.0, "5.143"),            # spirits floor 40% — 45 is in range
    ("Kentucky Straight Bourbon Whiskey", 50.0, "5.143"),
    ("Table Wine", 12.5, "4.21"),          # not over 14% — 12.5 in range
    ("Dessert Wine", 18.0, "4.21"),        # 14-24% — 18 in range
    ("Neutral Spirits", 96.0, "5.142"),    # at or above 95%
])
def test_in_range_abv_is_ok_with_citation(claim, abv, section):
    c = check_composition(claim, abv)
    assert c.status == "OK" and c.checked
    assert c.citation and c.citation["section"] == section
    assert c.citation["source_url"].startswith("https://")


@pytest.mark.parametrize("claim,abv,section", [
    ("Bourbon", 35.0, "5.143"),            # below the 40% spirits floor
    ("Whisky", 30.0, "5.143"),
    ("Table Wine", 16.0, "4.21"),          # over the 14% ceiling
    ("Dessert Wine", 10.0, "4.21"),        # below the 14% floor
    ("Dessert Wine", 26.0, "4.21"),        # above the 24% ceiling
])
def test_out_of_range_abv_is_review_never_reject(claim, abv, section):
    c = check_composition(claim, abv)
    assert c.status == "REVIEW" and c.checked        # advisory REVIEW...
    assert c.status not in {"FAIL", "FLAG", "REJECT"}  # ...never a confident reject
    assert c.citation and c.citation["section"] == section
    assert "please verify" in c.message and "never an auto-rejection" in c.message


def test_abv_envelope_boundaries_are_inclusive():
    # 40% exactly satisfies a "not less than 40%" floor; 14% a "not over 14%" ceiling.
    assert check_composition("Whisky", 40.0).status == "OK"
    assert check_composition("Table Wine", 14.0).status == "OK"


def test_no_op_when_no_claimed_abv():
    c = check_composition("Bourbon", None)
    assert not c.checked and c.status == "OK" and c.citation is None


def test_no_op_when_designation_unrecognized():
    c = check_composition("Unicorn Juice", 40.0)
    assert not c.checked and c.status == "OK" and c.citation is None


def test_no_op_when_class_has_no_cited_abv_bound():
    # 'Vodka' is recognized but carries no cited ABV envelope -> skipped, no flag.
    assert recognize("Vodka").recognized
    c = check_composition("Vodka", 5.0)
    assert not c.checked and c.status == "OK"


def test_composition_runs_offline(monkeypatch):
    real = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise OSError(f"offline test: blocked outbound to {host!r}")
        return real(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    assert check_composition("Bourbon", 35.0).status == "REVIEW"
