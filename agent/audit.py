"""Append-only, tamper-evident audit log for every write/override (who/what/when/why).

Required by the federal-audit context: a human-committed override must be
traceable *and* provably unaltered. The module exposes only *append* and *read* —
no update or delete path — so the trail can't be rewritten through this code. A
reason is mandatory.

Integrity (PRD 0004): every row carries a hash chain — `row_hash = SHA-256(prev_hash
‖ canonical(fields))`, the first row anchored to a fixed genesis seed — plus a
one-row `audit_chain_meta` checkpoint (count + head hash) so end-truncation is
detectable. `verify()` walks the chain and pinpoints any altered / deleted /
inserted / truncated row. Writes are serialized (an app lock + a `FOR UPDATE` tail
read on Postgres) so the inherently sequential chain can't fork under concurrent
writers. This is keyless tamper-*evidence* (detection), not prevention — see the
PRD non-goals (no WORM, no external notarization).

Storage is SQLAlchemy Core over a backend chosen at call time by
``config.audit_db_url()``: a local SQLite file by default (offline), or a durable
**Postgres** database when ``DATABASE_URL`` is set (PRD 0003). The same
dialect-agnostic code path runs on both.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

# NOTE: deliberately do NOT import `update`/`delete` here — the append-only contract
# is asserted by tests via `not hasattr(audit, "update"/"delete")`. Row inserts use
# insert(); the single-row checkpoint uses the Table.update() *method* on `_meta`.
from sqlalchemy import (Column, Integer, MetaData, Table, Text, create_engine,
                        func, insert, inspect, select, text)
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
    Column("prev_hash", Text),       # the chain link this row was computed from
    Column("row_hash", Text),        # SHA-256(prev_hash ‖ canonical(content fields))
)
# One-row checkpoint of the chain head, updated transactionally with every append.
# Lets verify() detect end-truncation (a truncated chain is otherwise internally
# valid). id is pinned to 1.
_meta = Table(
    "audit_chain_meta", _metadata,
    Column("id", Integer, primary_key=True),
    Column("row_count", Integer, nullable=False),
    Column("head_hash", Text, nullable=False),
)

# Content fields hashed into row_hash (NOT id/prev_hash/row_hash). Order is frozen:
# changing it would invalidate every existing hash.
_CONTENT = ["ts", "actor", "action", "target_result_id", "old_verdict",
            "new_verdict", "reason"]
_COLS = _CONTENT                                     # what recent() returns
_DUMP_COLS = ["id", *_CONTENT, "prev_hash", "row_hash"]   # what all_rows()/export use

# Fixed anchor for the first row's prev_hash. Versioned so a future scheme change is
# an explicit new genesis, never a silent collision.
GENESIS_HASH = hashlib.sha256(b"ttb-audit-chain/genesis/v1").hexdigest()


def _canonical(values: dict) -> str:
    """Stable serialization of a row's content fields for hashing. Fixed field order,
    JSON nulls for missing values, UTF-8 — identical on SQLite and Postgres."""
    return json.dumps([values.get(c) for c in _CONTENT],
                      ensure_ascii=False, separators=(",", ":"))


def _row_hash(prev_hash: str, values: dict) -> str:
    return hashlib.sha256((prev_hash + _canonical(values)).encode("utf-8")).hexdigest()


# Engines are pooled and thread-safe; cache one per resolved URL (keeping the pool
# alive) rather than reconnecting per call. Keyed by URL so a test that repoints
# config.AUDIT_DB transparently gets a fresh engine. The lock guards the cache-miss
# path so concurrent first-writers don't race on engine construction + schema setup.
_engines: dict[str, Engine] = {}
_engines_lock = threading.Lock()
# Serializes the read-tail → compute → insert step within this process so the chain
# can't fork. On Postgres the FOR UPDATE tail read extends that ordering across
# processes/replicas; on SQLite there is no such cross-process guarantee, so the
# SQLite backend is intended for single-process use (the durable, multi-writer path
# is Postgres). verify() also takes this lock for a consistent read snapshot.
_write_lock = threading.Lock()


def _ensure_schema(engine: Engine) -> None:
    """Create tables if absent, and add the hash columns to a pre-existing `audit`
    table (PRD 0003 DBs predate them). Idempotent; no back-fill of old rows."""
    _metadata.create_all(engine)             # creates missing tables only
    existing = {c["name"] for c in inspect(engine).get_columns("audit")}
    with engine.begin() as conn:
        for col in ("prev_hash", "row_hash"):
            if col not in existing:
                conn.execute(text(f"ALTER TABLE audit ADD COLUMN {col} VARCHAR"))


def _engine() -> Engine:
    url = config.audit_db_url()
    eng = _engines.get(url)
    if eng is not None:
        return eng
    with _engines_lock:
        eng = _engines.get(url)              # re-check under lock
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
            _ensure_schema(eng)
            _engines[url] = eng
    return eng


def record(actor: str, action: str, target_result_id: str | None,
           old_verdict: str | None, new_verdict: str | None, reason: str) -> int:
    """Append one immutable, hash-chained audit row. Raises if no reason is given."""
    if not reason or not reason.strip():
        raise ValueError("an audit reason is required")
    values = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "actor": actor, "action": action, "target_result_id": target_result_id,
        "old_verdict": old_verdict, "new_verdict": new_verdict,
        "reason": reason.strip(),
    }
    eng = _engine()
    # Serialize the whole read-tail → hash → insert → checkpoint step. The app lock
    # orders writers in-process; on Postgres the FOR UPDATE tail read additionally
    # orders them across processes/replicas (it is a no-op on SQLite — single-process).
    with _write_lock, eng.begin() as conn:
        tail = conn.execute(
            select(_audit.c.row_hash).order_by(_audit.c.id.desc())
            .limit(1).with_for_update()
        ).scalar()
        prev = tail if tail is not None else GENESIS_HASH
        rh = _row_hash(prev, values)
        new_id = int(conn.execute(
            insert(_audit).values(prev_hash=prev, row_hash=rh, **values)
        ).inserted_primary_key[0])
        count = conn.execute(select(func.count()).select_from(_audit)).scalar()
        if conn.execute(_meta.update().where(_meta.c.id == 1)
                        .values(row_count=count, head_hash=rh)).rowcount == 0:
            conn.execute(insert(_meta).values(id=1, row_count=count, head_hash=rh))
    return new_id


def recent(limit: int = 20) -> list[dict]:
    """Most-recent audit entries (read-only)."""
    cols = [_audit.c[name] for name in _COLS]
    stmt = select(*cols).order_by(_audit.c.id.desc()).limit(limit)
    with _engine().connect() as conn:
        rows = conn.execute(stmt).all()
    return [dict(zip(_COLS, r)) for r in rows]


def all_rows() -> list[dict]:
    """Every audit row, oldest first, including the row id and chain hashes
    (read-only). Unlike recent() this has no limit — the export needs the complete,
    independently-verifiable trail."""
    cols = [_audit.c[name] for name in _DUMP_COLS]
    stmt = select(*cols).order_by(_audit.c.id.asc())
    with _engine().connect() as conn:
        rows = conn.execute(stmt).all()
    return [dict(zip(_DUMP_COLS, r)) for r in rows]


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of verify(). `broken_position` is the offending row's id (or the
    expected next position for a truncation); `kind` is one of altered/deleted/
    inserted/truncated, or None when intact."""
    ok: bool
    broken_position: int | None
    kind: str | None
    message: str


def verify() -> VerifyResult:
    """Walk the hash chain oldest→newest and report integrity.

    Detects: an **altered** row (its stored row_hash no longer matches a recompute),
    a **deleted** or **inserted** row mid-chain (a broken prev_hash↔row_hash link),
    and an end-**truncated** chain (valid but shorter than the recorded checkpoint).
    Returns a VerifyResult pinpointing the first break.
    """
    cols = [_audit.c[name] for name in _DUMP_COLS]
    # Read the rows and the checkpoint under the write lock so a concurrent record()
    # can't commit between the two queries and yield a rows/checkpoint snapshot that
    # disagree (which would surface as a transient false tamper verdict).
    with _write_lock, _engine().connect() as conn:
        rows = [dict(zip(_DUMP_COLS, r)) for r in
                conn.execute(select(*cols).order_by(_audit.c.id.asc())).all()]
        head = conn.execute(
            select(_meta.c.row_count, _meta.c.head_hash).where(_meta.c.id == 1)
        ).first()

    expected_count = head[0] if head else None

    if not rows:
        if expected_count:
            return VerifyResult(False, 1, "truncated",
                                f"all {expected_count} row(s) missing — chain truncated")
        return VerifyResult(True, None, None, "chain intact (0 rows)")

    expected_prev = GENESIS_HASH
    for row in rows:
        if _row_hash(row["prev_hash"], row) != row["row_hash"]:
            return VerifyResult(False, row["id"], "altered",
                                f"row {row['id']}: content does not match its hash — altered")
        if row["prev_hash"] != expected_prev:
            # Linkage broke: a row was removed or inserted before this one. The
            # checkpoint count tells which — but only as a best-effort hint, since a
            # combined insert+delete preserves the count. Detection (ok=False) is the
            # authoritative property; the kind label is diagnostic.
            kind = "inserted" if expected_count is not None and len(rows) > expected_count else "deleted"
            return VerifyResult(False, row["id"], kind,
                                f"row {row['id']}: prev_hash does not link to the prior row — {kind}")
        expected_prev = row["row_hash"]

    # Chain is internally valid and linked. Reconcile against the checkpoint to catch
    # end-truncation, an extended tail, or a self-consistent tail-row alteration.
    if head is not None:
        if len(rows) < expected_count:
            return VerifyResult(False, len(rows) + 1, "truncated",
                                f"chain valid but {expected_count - len(rows)} tail row(s) "
                                "missing vs. checkpoint — truncated")
        if len(rows) > expected_count:
            return VerifyResult(False, expected_count + 1, "inserted",
                                "more rows than the checkpoint records — inserted at tail")
        if rows[-1]["row_hash"] != head[1]:
            # Same count + linked, but the tail hash disagrees with the checkpoint:
            # the last row was altered and its hash recomputed to stay self-consistent.
            return VerifyResult(False, rows[-1]["id"], "altered",
                                f"row {rows[-1]['id']}: tail hash does not match the "
                                "checkpoint head — altered")
    return VerifyResult(True, None, None, f"chain intact ({len(rows)} rows)")
