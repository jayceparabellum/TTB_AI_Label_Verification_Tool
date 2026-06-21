"""U2 — standards-of-identity recognition (app/standards.py).

Whole-token containment, never naive substring, fully offline. The false-positive
guard is load-bearing: a wrong recognition would wrongly PASS an invalid designation
(a confident-wrong verdict).
"""

import socket

import pytest

from app.standards import recognize


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
