"""Append-only audit log for every write/override (who/what/when/why).

Required by the federal-audit context: a human-committed override must be
traceable. The module exposes only *append* and *read* — no update or delete path
— so the trail can't be rewritten through this code. A reason is mandatory.

Storage is SQLAlchemy Core over a backend chosen at call time by
``config.audit_db_url()``: a local SQLite file by default (fully offline), or a
durable **Postgres** database when ``DATABASE_URL`` is set — so the trail survives
the redeploys that wipe an ephemeral disk. The same dialect-agnostic code path
runs on both; only the URL differs.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from sqlalchemy import (Column, Integer, MetaData, Table, Text, create_engine,
                        insert, select)
from sqlalchemy.engine import Engine

from . import config

_metadata = MetaData()
_audit = Table(
    "audit", _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", Text, nullable=False),
    Column("actor", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("target_result_id", Text),
    Column("old_verdict", Text),
    Column("new_verdict", Text),
    Column("reason", Text, nullable=False),
)
_COLS = ["ts", "actor", "action", "target_result_id", "old_verdict", "new_verdict", "reason"]

# Engines are pooled and thread-safe; cache one per resolved URL (keeping the
# pool alive) rather than reconnecting per call. Keyed by URL so a test that
# repoints config.AUDIT_DB transparently gets a fresh engine. The lock guards the
# cache-miss path so concurrent first-writers don't race on engine construction +
# CREATE TABLE (checkfirst is not atomic across connections).
_engines: dict[str, Engine] = {}
_engines_lock = threading.Lock()


def _engine() -> Engine:
    url = config.audit_db_url()
    eng = _engines.get(url)
    if eng is not None:
        return eng
    with _engines_lock:
        eng = _engines.get(url)          # re-check under lock
        if eng is None:
            if url.startswith("sqlite"):
                # check_same_thread=False: the engine pool hands connections across
                # threads (FastAPI workers). timeout: wait out SQLite's single-writer
                # lock under concurrent writes instead of raising "database is locked".
                eng = create_engine(
                    url, future=True,
                    connect_args={"check_same_thread": False, "timeout": 30},
                )
            else:
                eng = create_engine(url, future=True, pool_pre_ping=True)
            _metadata.create_all(eng)    # idempotent: CREATE TABLE IF NOT EXISTS
            _engines[url] = eng
    return eng


def record(actor: str, action: str, target_result_id: str | None,
           old_verdict: str | None, new_verdict: str | None, reason: str) -> int:
    """Append one immutable audit row. Raises if no reason is given."""
    if not reason or not reason.strip():
        raise ValueError("an audit reason is required")
    ts = datetime.now(timezone.utc).isoformat()
    with _engine().begin() as conn:
        result = conn.execute(insert(_audit).values(
            ts=ts, actor=actor, action=action, target_result_id=target_result_id,
            old_verdict=old_verdict, new_verdict=new_verdict, reason=reason.strip(),
        ))
        return int(result.inserted_primary_key[0])


def recent(limit: int = 20) -> list[dict]:
    """Most-recent audit entries (read-only)."""
    cols = [_audit.c[name] for name in _COLS]
    stmt = select(*cols).order_by(_audit.c.id.desc()).limit(limit)
    with _engine().connect() as conn:
        rows = conn.execute(stmt).all()
    return [dict(zip(_COLS, r)) for r in rows]


# Full-dump columns include the row id (recent() hides it). Stable insertion order
# (oldest → newest by id) so an export reads chronologically and is reproducible.
_DUMP_COLS = ["id", *_COLS]


def all_rows() -> list[dict]:
    """Every audit row, oldest first, including the row id (read-only).

    Unlike recent() this has no limit — the export needs the complete trail.
    """
    cols = [_audit.c[name] for name in _DUMP_COLS]
    stmt = select(*cols).order_by(_audit.c.id.asc())
    with _engine().connect() as conn:
        rows = conn.execute(stmt).all()
    return [dict(zip(_DUMP_COLS, r)) for r in rows]
