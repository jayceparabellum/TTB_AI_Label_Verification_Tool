"""U5 — append-only audit log: records writes, requires a reason, no mutation path."""

import pytest

from agent import audit, config


@pytest.fixture(autouse=True)
def _tmp_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_DB", tmp_path / "audit.sqlite")
    yield


def test_record_appends_row():
    audit.record("agent-user", "override", "r1", "FLAG", "PASS",
                 "manual review confirms the warning is compliant")
    rows = audit.recent()
    assert len(rows) == 1
    row = rows[0]
    assert row["actor"] == "agent-user" and row["action"] == "override"
    assert row["new_verdict"] == "PASS" and row["old_verdict"] == "FLAG"
    assert row["reason"].startswith("manual review") and row["ts"]


def test_reason_is_required():
    with pytest.raises(ValueError):
        audit.record("a", "override", "r1", "FLAG", "PASS", "   ")
    assert audit.recent() == []          # nothing written


def test_append_only_no_mutation_api():
    assert not hasattr(audit, "update") and not hasattr(audit, "delete")
    audit.record("a", "override", "r1", None, "PASS", "reason one")
    audit.record("a", "override", "r2", None, "FLAG", "reason two")
    rows = audit.recent()
    assert len(rows) == 2                 # both retained
    assert rows[0]["target_result_id"] == "r2"   # newest first
