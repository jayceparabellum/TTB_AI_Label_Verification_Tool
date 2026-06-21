"""Check the integrity of the append-only audit log (PRD 0004).

Walks the hash chain via `agent.audit.verify()` and reports whether the trail is
intact or has been altered / deleted / inserted / truncated — an on-demand integrity
check an auditor can run against whatever backend is configured (local SQLite by
default, or Postgres when DATABASE_URL is set).

Exit code 0 = intact, 1 = tampered (so it can gate a CI/cron check). The verdict is
deterministic and read-only — it never writes to the log.

Run:
  python scripts/verify_audit.py            # human-readable
  python scripts/verify_audit.py --json     # machine-readable
  DATABASE_URL=postgres://... python scripts/verify_audit.py   # against Postgres
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `agent` importable when this script is run standalone (python scripts/...).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import audit, config  # noqa: E402


def _backend_label() -> str:
    """A safe description of the backend under check — never prints DSN credentials."""
    return "Postgres (DATABASE_URL)" if config.DATABASE_URL else f"SQLite ({config.AUDIT_DB})"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    as_json = "--json" in argv

    result = audit.verify()

    if as_json:
        print(json.dumps({
            "ok": result.ok,
            "broken_position": result.broken_position,
            "kind": result.kind,
            "message": result.message,
            "backend": _backend_label(),
        }))
    elif result.ok:
        print(f"✓ audit chain intact — {result.message}  [{_backend_label()}]")
    else:
        print(f"✗ audit chain FAILED — {result.kind} at position "
              f"{result.broken_position}: {result.message}  [{_backend_label()}]")

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
