"""PRD 0004 — tamper-evident audit log: hash chain + verify() detection.

verify() must pass on an intact chain and pinpoint every tamper kind (altered /
deleted / inserted / truncated). Tampers are applied by writing the DB directly,
bypassing the append-only record() path and leaving the chain-head checkpoint
untouched — exactly what an attacker editing only the audit table would do.
"""

import csv
import io

import pytest
from sqlalchemy import text

from agent import audit, config
from app import audit_export


@pytest.fixture(autouse=True)
def _isolated_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_DB", tmp_path / "audit.sqlite")
    monkeypatch.setattr(config, "DATABASE_URL", "")
    monkeypatch.setattr(audit, "_engines", {})
    yield


def _seed(n: int) -> list[int]:
    return [audit.record("agent-user", "override", f"r{i}", "FLAG", "PASS",
                         f"reason {i}") for i in range(n)]


def _exec(sql: str, **params):
    with audit._engine().begin() as conn:
        conn.execute(text(sql), params)


# --- intact ------------------------------------------------------------------

def test_intact_chain_verifies():
    _seed(5)
    res = audit.verify()
    assert res.ok and res.kind is None and res.broken_position is None
    assert "5 rows" in res.message


def test_empty_chain_is_intact():
    res = audit.verify()
    assert res.ok and res.kind is None


# --- altered -----------------------------------------------------------------

def test_altered_row_is_detected_and_pinpointed():
    ids = _seed(5)
    target = ids[2]
    _exec("UPDATE audit SET reason = 'tampered' WHERE id = :i", i=target)
    res = audit.verify()
    assert not res.ok and res.kind == "altered" and res.broken_position == target


def test_altering_genesis_row_is_detected():
    ids = _seed(3)
    _exec("UPDATE audit SET new_verdict = 'NOPE' WHERE id = :i", i=ids[0])
    res = audit.verify()
    assert not res.ok and res.kind == "altered" and res.broken_position == ids[0]


# --- deleted -----------------------------------------------------------------

def test_deleted_middle_row_breaks_the_link():
    ids = _seed(5)
    _exec("DELETE FROM audit WHERE id = :i", i=ids[2])     # checkpoint NOT updated
    res = audit.verify()
    assert not res.ok and res.kind == "deleted"
    assert res.broken_position == ids[3]                   # first row that no longer links


def test_deleting_genesis_row_breaks_genesis_anchor():
    ids = _seed(4)
    _exec("DELETE FROM audit WHERE id = :i", i=ids[0])
    res = audit.verify()
    # The new first row's prev_hash != GENESIS_HASH.
    assert not res.ok and res.kind == "deleted" and res.broken_position == ids[1]


# --- inserted ----------------------------------------------------------------

def test_inserted_row_is_detected():
    _seed(4)
    # A *self-consistent* forged row (its row_hash is correctly computed, so the
    # per-row check passes) appended with a prev_hash that does NOT link to the real
    # tail; the checkpoint still says 4. Only the linkage + count reveal it.
    content = {"ts": "2026-01-01T00:00:00+00:00", "actor": "mallory",
               "action": "override", "target_result_id": None, "old_verdict": None,
               "new_verdict": None, "reason": "forged"}
    forged_prev = "deadbeef"
    forged_hash = audit._row_hash(forged_prev, content)
    _exec("INSERT INTO audit (ts, actor, action, reason, prev_hash, row_hash) "
          "VALUES (:ts, :actor, :action, :reason, :prev, :rh)",
          ts=content["ts"], actor=content["actor"], action=content["action"],
          reason=content["reason"], prev=forged_prev, rh=forged_hash)
    res = audit.verify()
    assert not res.ok and res.kind == "inserted"


# --- truncated ---------------------------------------------------------------

def test_truncated_tail_is_detected_against_checkpoint():
    ids = _seed(5)
    # Drop the last two rows but leave the chain-head checkpoint claiming 5.
    _exec("DELETE FROM audit WHERE id IN (:a, :b)", a=ids[4], b=ids[3])
    res = audit.verify()
    assert not res.ok and res.kind == "truncated"
    assert res.broken_position == 4               # first missing position (1-based)


def test_self_consistent_tail_alteration_is_classified_altered():
    # The realistic attack: edit the LAST row and recompute its row_hash so the
    # per-row + linkage checks pass; only the checkpoint head still holds the old hash.
    # This must report 'altered' at the tail row — not 'truncated' with "0 missing".
    ids = _seed(4)
    tail = audit.all_rows()[-1]
    forged = {**{k: tail[k] for k in audit._CONTENT}, "reason": "TAMPERED"}
    forged_hash = audit._row_hash(tail["prev_hash"], forged)
    _exec("UPDATE audit SET reason = 'TAMPERED', row_hash = :h WHERE id = :i",
          h=forged_hash, i=ids[-1])
    res = audit.verify()
    assert not res.ok and res.kind == "altered" and res.broken_position == ids[-1]


# --- export carries a verifiable chain ---------------------------------------

def test_export_includes_hash_columns_and_stays_consistent():
    _seed(3)
    assert "prev_hash" in audit_export.COLUMNS and "row_hash" in audit_export.COLUMNS

    rows = audit.all_rows()
    assert all(r["prev_hash"] and r["row_hash"] for r in rows)

    csv_text = audit_export.audit_to_csv(rows)
    header = next(csv.reader(io.StringIO(csv_text)))
    assert header[-2:] == ["prev_hash", "row_hash"]

    # The exported chain links head-to-tail (independently checkable from the CSV).
    parsed = list(csv.DictReader(io.StringIO(csv_text)))
    for prev, cur in zip(parsed, parsed[1:]):
        assert cur["prev_hash"] == prev["row_hash"]
