# PRD 0004: Tamper-Evident Audit Storage

- **Status:** Implemented (2026-06-21)
- **Author:** jayceparabellum
- **Created:** 2026-06-21

## Summary

Make the append-only audit log tamper-evident with a per-row hash chain and a
`verify()` routine that detects — and pinpoints — any alteration, deletion,
insertion, or end-truncation of the who/what/when/why trail. Follow-on to PRD 0003,
which made the log durable but not integrity-checked.

## Problem

PRD 0003 made the audit log **durable** (it survives redeploys on Postgres), but
durability isn't **integrity**. A database admin, a leaked credential, or a
compromised host can still silently `UPDATE` or `DELETE` rows, and nothing in the
system would reveal it. In a federal-audit setting the trail of who decided what and
why must be not just present but **provably unaltered** — auditors, and the agency
defending a decision, need to both **detect** tampering and produce a **positive,
verifiable proof** that the trail is intact. Today there is no such check.

## Goals / Success Criteria

Concrete, observable signals (checkable in a test or demo):

- **Verify passes on an intact chain; fails on any tamper.** `verify()` returns OK
  over an unmodified log; mutate or delete any stored row and it fails.
- **Pinpoints the break.** On failure it reports *which* row/position broke and *how*
  — altered vs. deleted vs. inserted.
- **Genesis-anchored.** The chain is pinned to a fixed genesis seed, so the start of
  the chain is itself verifiable (a rewritten history can't fake a new beginning).
- **Detects end-truncation.** Deleting the most-recent rows (not just mid-chain edits)
  is caught.
- **CI-gated.** A test/CI check asserts the chain stays intact, making tamper-evidence
  a standing guarantee rather than a one-off tool.

## Non-goals

Explicitly **not** success for this PRD:

- **Migrating existing rows.** No back-fill of hashes onto current POC/ephemeral audit
  rows — the chain may start fresh at a genesis row.
- **Key management / HSM.** No secret-key infrastructure, rotation, or HSM; a keyless
  hash chain (or a single configured key) is acceptable for this cut.
- **Tamper alerting / monitoring.** No automated alerts or dashboards on verify
  failure; detection is on-demand via the verify routine.
- **UI surfacing.** No web UI for chain status; verify is programmatic / CLI.
- **External notarization** (blockchain / public timestamp authority), **encryption /
  confidentiality** of audit contents, **WORM / true immutability** (tampering is
  *detectable*, not *prevented*), and **signed-identity / non-repudiation** of *which*
  human authored each row — chain integrity only.

## Scope

### In scope

The minimum cut that ships:

- A **per-row hash chain** added inline to `agent/audit.py`: each row stores
  `row_hash = H(prev_hash ‖ canonical(row fields))` and the `prev_hash` it chained
  from; the first row chains from a fixed **genesis seed**.
- A public **`audit.verify()`** that walks the log oldest→newest, recomputes each
  hash, checks linkage + genesis, **detects end-truncation**, and **pinpoints** the
  first break and its kind (see the verify contract below).
- **Serialized writes** so the sequential chain can't fork under concurrent writers.
- `record()` stays **append-only** (no update/delete path).
- The **CSV / Excel export** carries `prev_hash` + `row_hash`, so an exported trail is
  independently verifiable outside the app.
- A **test / CI gate** asserting an intact freshly-built chain verifies, and that
  representative tampers (edit, delete, insert, truncate) are caught.

### Out of scope

- Everything in **Non-goals** above.
- ~~A standalone auditor CLI/route~~ — added as a follow-up: `scripts/verify_audit.py`
  wraps `verify()` for an on-demand integrity check (exit 0 intact / 1 tampered,
  `--json` for machines), runnable against SQLite or Postgres. A web route/chat tool
  remains optional.

## Proposed Design

### New services / components

- **Inline in `agent/audit.py`:**
  - `record()` gains chaining — read the current chain tail's `row_hash`, compute the
    new row's `row_hash` over a **stable canonical serialization** of its fields, and
    insert both `prev_hash` and `row_hash` atomically with the row.
  - **Write serialization** (resolves the fork risk): `record()` performs the
    read-tail → compute → insert as one serialized step. (a) An app-level write lock
    covers the single-process default (one uvicorn worker); (b) on Postgres the tail
    read uses `SELECT … ORDER BY id DESC LIMIT 1 FOR UPDATE` **inside the same
    transaction** as the `INSERT`, so even across replicas two writers cannot chain off
    the same `prev_hash`. SQLite is single-writer already (busy-timeout from PRD 0003).
  - `verify()` (new public function) — walk rows in insertion order, recompute each
    `row_hash` from the stored `prev_hash` + canonical fields, assert each row's
    `prev_hash` equals the prior row's `row_hash`, assert the genesis link, and assert
    the chain isn't truncated. **Returns a structured result:**
    `ok: bool` · `broken_position: int | None` (the `id` of the first bad row, or the
    expected position for a deletion/truncation) · `kind: "altered" | "deleted" |
    "inserted" | "truncated" | None` · `message: str` (human-readable, e.g. "row 42:
    stored row_hash does not match recomputed hash — altered"). On an intact chain:
    `{ok: True, broken_position: None, kind: None, message: "chain intact (N rows)"}`.
  - Hashing via **`hashlib`** (SHA-256); canonical serialization with fixed field
    order, explicit null handling, UTF-8 — identical output on SQLite and Postgres.

### Existing code touched

- `agent/audit.py` — the SQLAlchemy `audit` table gains `prev_hash` / `row_hash`
  columns; `record()` chains; `verify()` added.
- `app/audit_export.py` — **include** `prev_hash` + `row_hash` in the CSV/XLSX column
  set so an exported trail is independently verifiable offline.
- Tests — a new suite that builds a chain in-test and asserts `verify()` returns
  `ok` on an intact chain and the correct `kind` + `broken_position` for each tamper
  (altered field, deleted row, inserted row, truncated tail), applied directly via the
  engine. This suite **is** the CI gate (it runs in the existing pytest job — the live
  runtime log is not committable, so the guarantee is over an in-test chain).

### Data model changes

- Add **`prev_hash`** and **`row_hash`** (Text) columns to the `audit` table.
- The genesis row's `prev_hash` is a fixed seed constant.
- A one-row **`audit_chain_meta`** checkpoint table (`row_count`, `head_hash`),
  updated transactionally with each append. *Added at implementation:* end-truncation
  can't be detected from the chain alone (a truncated chain is still internally
  valid), so a persisted head is required to catch it. Kept in the same DB — still no
  external notarization (a non-goal); an attacker who edits both tables isn't stopped
  (keyless tamper-*evidence*, not prevention).
- **No migration of existing rows** (a non-goal): for an already-populated table,
  `ALTER TABLE ADD COLUMN` and begin the chain at the first new row; pre-existing rows
  are treated as pre-genesis / unchained.

_Implemented 2026-06-21: chain + `verify()` inline in `agent/audit.py`, hash columns
in the export, and a tamper-detection suite (`tests/test_audit_tamper.py`) covering all
four kinds — wired into the existing pytest/CI job._

### External dependencies

- **None** — `hashlib` is in the standard library.

## Open questions

- How exactly should **pre-existing unchained rows** in an already-populated table be
  treated — fresh genesis at the first new row (default, since back-fill is a non-goal)
  vs. a one-time backfill? Confirm the fresh-genesis default.
- **Canonical serialization** details to freeze at implementation so a later schema
  addition can't silently break old hashes: exact column set + ordering, `ts` format
  (already ISO-8601 UTC), and the null representation.
- **Write-serialization throughput.** The `FOR UPDATE` tail lock serializes all audit
  writes; at POC volume this is negligible, but confirm it's acceptable (or revisit) if
  write rates ever climb.

_Resolved during refinement (2026-06-21): write-ordering → app lock + `FOR UPDATE`
tail read; export → includes hash columns; CI gate → in-test chain + tamper suite in
the existing pytest job; verify() → structured `{ok, broken_position, kind, message}`._

## References

- [docs/prds/0003-durable-audit-storage.md](0003-durable-audit-storage.md) — the
  durability prerequisite this builds on.
- [PRD.md](../../PRD.md) — "Open questions": tamper-evident audit storage.
- `agent/audit.py` (the append-only store + chaining seam), `app/audit_export.py`.
