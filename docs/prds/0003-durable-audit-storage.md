# PRD 0003: Durable Audit Storage

- **Status:** Draft
- **Author:** jayceparabellum
- **Created:** 2026-06-20

## Summary

Move the append-only audit log (and the LangGraph conversation checkpoints) off
ephemeral SQLite on Render's disk onto a managed, persistent Postgres backend so
the human-gated approval trail survives redeploys and concurrent writes.

## Problem

The append-only audit log (`agent/audit.py`) and the agent's checkpoint DB
(`SqliteSaver` in `app/agent_chat.py`) both live in SQLite on Render's
**ephemeral disk, which resets on every redeploy**. Compliance reviewers lose the
human-committed override/approval history — the very record the federal-audit
context requires to be traceable. Today a redeploy silently wipes the trail.

## Goals / Success Criteria

Concrete, observable signals (checkable in a test or demo):

- **Survives redeploy/restart.** Record an approval → trigger a redeploy or
  restart → the audit entry (and its CSV/Excel export) is still present and
  identical.
- **Concurrency-safe.** Parallel approvals don't drop or corrupt rows; the log
  stays consistent under concurrent writes.
- The existing export (`app/audit_export.py`, CSV + XLSX over `all_rows()`) keeps
  working unchanged against the durable backend.

## Non-goals

Explicitly **not** success for this PRD:

- **Tamper-evidence.** Cryptographic append-only / hash-chained integrity is a
  separate future PRD — not required here. Persistence is the problem being solved.
- **Retention / purge policy.** No automated retention windows, archival, or purge
  of old entries.
- **Zero-downtime migration.** Migrating existing ephemeral rows with zero downtime
  is not required; the POC can start the durable log fresh.
- **Backups / DR.** Formal backup cadence and a disaster-recovery runbook are out
  of scope.

## Scope

### In scope

The minimum cut that ships:

- Swap ephemeral SQLite for a **managed Postgres backend** behind the existing
  audit interface (`record` / `recent` / `all_rows`), with the export still working.
- Make the **LangGraph checkpointer durable** on the same Postgres (replace the
  `SqliteSaver` in `app/agent_chat.py`).
- The durable backend is **concurrency-safe**.

### Out of scope

Things a reader might assume are included but are not:

- **Multi-user / auth** — no user accounts, roles, or per-reviewer identity; stays
  single-user POC (a standing non-goal in `STRATEGY.md`).
- **External SIEM / export** — no shipping audit events to an external logging or
  compliance system.
- **Persisting uploads / PII** — still nothing-at-rest for label images or PII; only
  the verdict/approval audit metadata is stored.
- **COLA integration** — no write-back to any TTB/COLA system; the audit log stays
  internal.
- The four non-goals above (tamper-evidence, retention, zero-downtime migration,
  backups/DR).

## Proposed Design

### New services / components

- A durable storage backend for the audit log, selected by environment
  (`DATABASE_URL` present → Postgres; absent → today's local SQLite, preserving the
  offline-by-default invariant). _Exact wiring shape — backend behind the existing
  `agent/audit.py` seam vs. a new `audit_store` module vs. a repository/driver split
  — is unresolved; see Open questions._
- A **Postgres-backed LangGraph checkpointer** replacing the `SqliteSaver`.

### Existing code touched

- `agent/audit.py` — the storage layer behind `record` / `recent` / `all_rows`
  (the append-only seam; callers should be unaffected).
- `app/agent_chat.py` — `SqliteSaver(sqlite3.connect(config.CHECKPOINT_DB, …))`
  swapped for the Postgres checkpointer.
- `agent/config.py` — `AUDIT_DB` / `CHECKPOINT_DB` path config + a new `DATABASE_URL`.
- `app/audit_export.py` — reads `all_rows()`; expected to be **unchanged**.
- `Dockerfile.agent` / `render.yaml` — provision the Postgres service and wire
  `DATABASE_URL`.

### Data model changes

- The existing `audit` table ported to Postgres (columns unchanged: `id`, `ts`,
  `actor`, `action`, `target_result_id`, `old_verdict`, `new_verdict`, `reason`).
- LangGraph Postgres checkpoint tables (the saver's own schema).
- A bootstrap/migration step that creates these tables on first connect.

### External dependencies

- **Managed Render Postgres**, reached via `DATABASE_URL`, with **`psycopg`** as the
  driver.
- The LangGraph Postgres checkpoint saver package (e.g. `langgraph-checkpoint-postgres`).

## Open questions

- How should the durable backend be wired into `agent/audit.py` — keep the
  `record`/`recent`/`all_rows` API and route by `DATABASE_URL`, extract a dedicated
  `audit_store` module, or introduce a repository + driver split? (Left unanswered in
  interrogation.)
- Should the **offline/local default stay SQLite** when `DATABASE_URL` is unset, to
  preserve the "offline by default / nothing leaves the network" invariant?
- Does making **conversation checkpoints durable** in Postgres conflict with the
  "nothing persisted / no PII at rest" invariant, given checkpoint state can contain
  label text? Even though retention policy is a non-goal, a scoping decision is needed.
- Exact LangGraph Postgres saver package + version, and its schema-migration story.

## Post-merge verification

Implemented in **PR #43** (audit log + checkpoints on SQLAlchemy Core, Postgres
selected by `DATABASE_URL`). The live Postgres path was **config-tested only** — no
Postgres server was available in the implementation environment — so the SQLite
same-code-path tests stand in for it. Before relying on the durable backend in
production:

- [ ] **Run the live Postgres round-trip.** Either let Render's managed Postgres
  (declared in `render.yaml`) wire up `DATABASE_URL` on deploy, or run the gated
  test locally: `TEST_DATABASE_URL=<dsn> pytest tests/test_durable_audit.py::test_postgres_round_trip`.
- [ ] **Confirm an approval survives a real redeploy** on Render — record an
  override, trigger a redeploy, verify the audit entry + its export are still present.
- [ ] **Verify the Postgres checkpointer** (`PostgresSaver.setup()` + interrupt/resume)
  against a live database — this branch is lazy-imported and untested here.
- [ ] **Revisit the PII/checkpoint scoping question** (below) once durable checkpoints
  are observed in production, since checkpoint state can contain label text.

## References

- [PRD.md](../../PRD.md) — "Open questions": durable, tamper-evident audit storage.
- [docs/prds/0001-audit-log-export.md](0001-audit-log-export.md) — the export this must keep working.
- `agent/audit.py`, `app/agent_chat.py`, `app/audit_export.py`, `agent/config.py`.
