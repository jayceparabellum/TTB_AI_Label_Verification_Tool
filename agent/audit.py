"""Append-only audit log for every write/override (who/what/when/why).

Required by the federal-audit context: a human-committed override must be
traceable. The module exposes only *append* and *read* — no update or delete path
— so the trail can't be rewritten through this code. A reason is mandatory.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target_result_id TEXT,
    old_verdict TEXT,
    new_verdict TEXT,
    reason TEXT NOT NULL
)
"""
_COLS = ["ts", "actor", "action", "target_result_id", "old_verdict", "new_verdict", "reason"]


def _conn() -> sqlite3.Connection:
    config.ensure_data_dir()
    c = sqlite3.connect(config.AUDIT_DB, check_same_thread=False)
    c.execute(_SCHEMA)
    return c


def record(actor: str, action: str, target_result_id: str | None,
           old_verdict: str | None, new_verdict: str | None, reason: str) -> int:
    """Append one immutable audit row. Raises if no reason is given."""
    if not reason or not reason.strip():
        raise ValueError("an audit reason is required")
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        cur = c.execute(
            f"INSERT INTO audit ({','.join(_COLS)}) VALUES (?,?,?,?,?,?,?)",
            (ts, actor, action, target_result_id, old_verdict, new_verdict, reason.strip()),
        )
        return cur.lastrowid


def recent(limit: int = 20) -> list[dict]:
    """Most-recent audit entries (read-only)."""
    with _conn() as c:
        rows = c.execute(
            f"SELECT {','.join(_COLS)} FROM audit ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(zip(_COLS, r)) for r in rows]


# Full-dump columns include the row id (recent() hides it). Stable insertion order
# (oldest → newest by id) so an export reads chronologically and is reproducible.
_DUMP_COLS = ["id", *_COLS]


def all_rows() -> list[dict]:
    """Every audit row, oldest first, including the row id (read-only).

    Unlike recent() this has no limit — the export needs the complete trail.
    """
    with _conn() as c:
        rows = c.execute(
            f"SELECT {','.join(_DUMP_COLS)} FROM audit ORDER BY id ASC"
        ).fetchall()
    return [dict(zip(_DUMP_COLS, r)) for r in rows]
