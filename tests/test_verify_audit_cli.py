"""scripts/verify_audit.py — on-demand audit-chain integrity check (PRD 0004).

Exit 0 when the hash chain is intact, 1 when tampered; the backend label never
leaks DSN credentials.
"""

import json

import pytest
from sqlalchemy import text

from agent import audit, config
from scripts import verify_audit


@pytest.fixture(autouse=True)
def _isolated_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_DB", tmp_path / "audit.sqlite")
    monkeypatch.setattr(config, "DATABASE_URL", "")
    monkeypatch.setattr(audit, "_engines", {})
    yield


def _seed(n):
    return [audit.record("u", "override", f"r{i}", None, "PASS", f"reason {i}")
            for i in range(n)]


def test_intact_chain_exits_zero(capsys):
    _seed(3)
    assert verify_audit.main([]) == 0
    assert "intact" in capsys.readouterr().out


def test_tampered_chain_exits_one(capsys):
    ids = _seed(4)
    with audit._engine().begin() as c:        # delete a row out-of-band
        c.execute(text("DELETE FROM audit WHERE id = :i"), {"i": ids[1]})
    assert verify_audit.main([]) == 1
    out = capsys.readouterr().out
    assert "FAILED" in out and "deleted" in out


def test_json_output_is_machine_readable(capsys):
    _seed(2)
    assert verify_audit.main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True and payload["message"].startswith("chain intact")


def test_empty_chain_is_intact(capsys):
    assert verify_audit.main([]) == 0


def test_backend_label_never_leaks_credentials(monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", "postgres://user:secret@host:5432/db")
    label = verify_audit._backend_label()
    assert "secret" not in label and label == "Postgres (DATABASE_URL)"
