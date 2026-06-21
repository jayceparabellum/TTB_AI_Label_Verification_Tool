"""PRD 0003 — durable, concurrency-safe audit storage + DATABASE_URL backend select.

The audit log runs on SQLAlchemy Core over a backend chosen by DATABASE_URL:
local SQLite by default (offline), durable Postgres when set. These tests cover
the two success criteria on the SQLite path that the *same* code runs on Postgres
(survives a reconnect; consistent under concurrent writes), the URL routing, and
the checkpointer's backend selection. A live-Postgres round-trip runs only when
TEST_DATABASE_URL is provided.
"""

import os
import sys
import threading
import types

import pytest

from agent import audit, config


@pytest.fixture(autouse=True)
def _isolated_audit(tmp_path, monkeypatch):
    # Point the audit log at a throwaway file and a clean engine cache, with no
    # DATABASE_URL so the default SQLite path is exercised.
    monkeypatch.setattr(config, "AUDIT_DB", tmp_path / "audit.sqlite")
    monkeypatch.setattr(config, "DATABASE_URL", "")
    monkeypatch.setattr(audit, "_engines", {})
    yield


# --- success criterion 1: survives a redeploy/restart -------------------------

def test_rows_survive_engine_reconnect():
    audit.record("agent-user", "override", "r1", "FLAG", "PASS", "first commit")
    audit.record("agent-user", "override", "r2", None, "FLAG", "second commit")

    # The file is real on-disk storage, not in-memory state.
    assert config.AUDIT_DB.exists()

    # Simulate a process restart: drop every cached engine/connection, then read
    # back through a freshly built engine pointed at the same file.
    for eng in audit._engines.values():
        eng.dispose()
    audit._engines.clear()

    rows = audit.all_rows()
    assert [r["target_result_id"] for r in rows] == ["r1", "r2"]   # both persisted
    assert [r["reason"] for r in rows] == ["first commit", "second commit"]


# --- success criterion 2: concurrency-safe ------------------------------------

def test_concurrent_writes_are_consistent():
    n = 40
    start = threading.Barrier(n)

    def writer(i: int):
        start.wait()                       # release all writers together
        audit.record("agent-user", "override", f"r{i}", None, "PASS",
                     f"concurrent reason {i}")

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = audit.all_rows()
    assert len(rows) == n                                  # nothing dropped
    assert len({r["id"] for r in rows}) == n               # ids unique
    assert {r["target_result_id"] for r in rows} == {f"r{i}" for i in range(n)}


# --- DATABASE_URL routing -----------------------------------------------------

def test_audit_url_defaults_to_sqlite_file(monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", "")
    url = config.audit_db_url()
    assert url.startswith("sqlite:///") and url.endswith("audit.sqlite")


@pytest.mark.parametrize("dsn", [
    "postgres://u:p@host:5432/db",
    "postgresql://u:p@host:5432/db",
])
def test_audit_url_normalizes_postgres_dsn(monkeypatch, dsn):
    monkeypatch.setattr(config, "DATABASE_URL", dsn)
    assert config.audit_db_url() == "postgresql+psycopg://u:p@host:5432/db"


@pytest.mark.parametrize("url,expected", [
    ("postgres://x", True),
    ("postgresql://x", True),
    ("postgresql+psycopg://x", True),
    ("sqlite:///audit.sqlite", False),
    ("", False),
])
def test_is_postgres_url(url, expected):
    assert config.is_postgres_url(url) is expected


# --- checkpointer backend selection -------------------------------------------

def test_make_saver_defaults_to_sqlite(monkeypatch, tmp_path):
    from langgraph.checkpoint.sqlite import SqliteSaver
    from app import agent_chat

    monkeypatch.setattr(config, "DATABASE_URL", "")
    monkeypatch.setattr(config, "CHECKPOINT_DB", tmp_path / "checkpoints.sqlite")
    saver = agent_chat._make_saver()
    assert isinstance(saver, SqliteSaver)


def test_make_saver_uses_postgres_when_database_url_set(monkeypatch):
    """The postgres branch (lazy-imported, no live PG here) is selected and wired:
    from_conn_string(DSN) -> setup() -> return the saver."""
    from app import agent_chat

    calls = {}

    class _FakeSaver:
        def setup(self):
            calls["setup"] = True

    class _FakeCM:
        def __enter__(self):
            return _FakeSaver()

        def __exit__(self, *a):
            return False

    class _FakePostgresSaver:
        @classmethod
        def from_conn_string(cls, dsn):
            calls["dsn"] = dsn
            return _FakeCM()

    fake_mod = types.ModuleType("langgraph.checkpoint.postgres")
    fake_mod.PostgresSaver = _FakePostgresSaver
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.postgres", fake_mod)
    monkeypatch.setattr(config, "DATABASE_URL", "postgres://u:p@host/db")

    saver = agent_chat._make_saver()
    assert isinstance(saver, _FakeSaver)
    assert calls["dsn"] == "postgres://u:p@host/db"   # raw DSN to psycopg, not normalized
    assert calls["setup"] is True


# --- live Postgres round-trip (opt-in) ----------------------------------------

@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"),
                    reason="set TEST_DATABASE_URL to run the live Postgres round-trip")
def test_postgres_round_trip(monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setattr(audit, "_engines", {})
    rid = "pg-roundtrip"
    audit.record("agent-user", "override", rid, "FLAG", "PASS", "postgres durability")
    assert any(r["target_result_id"] == rid for r in audit.all_rows())
