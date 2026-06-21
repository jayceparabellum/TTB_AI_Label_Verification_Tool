# PRD 0001: Audit Log CSV/Excel Export

- **Status:** Implemented (2026-06-19)
- **Author:** jayceparabellum
- **Created:** 2026-06-19

## Summary

Let a user export the append-only audit log as both a CSV and an Excel (.xlsx) file, offered through an in-chat tool the assistant can hand back as downloads.

## Problem

Every human-gated write (override, manual entry, batch run) is recorded to an append-only audit log in `agent/audit.py` (a SQLite table). Today that trail only exists in-process / in the database — there is no user-facing way to extract it for external compliance review, recordkeeping, or sharing. A compliance agent who needs to hand the decision history to a reviewer has no path to get it out of the app.

> _Who feels it and any external trigger (e.g. an audit/recordkeeping requirement) were not specified during intake — see Open questions._

## Goals / Success Criteria

- An in-chat request ("export the audit log") returns the **full** audit log as a CSV **and** an .xlsx file, surfaced as two download buttons in the same chat turn.
- The exported content is provably correct via a **round-trip test**: record known audit rows → export → parse the CSV/XLSX back → assert the parsed rows match the recorded rows (count, fields, order).
- Both files contain every audit row with all recorded fields (actor, action, target result id, old/new verdict, reason, timestamp).
- The export is a **plain read** — it flows through with no confirm gate and produces **no** new audit entry for the export itself.
- Existing chat, verify, and batch flows are unaffected (the change is additive).

## Non-goals

- Filtering the export (by date range, actor, or action) — deferred to a follow-up; the first cut exports all rows.
- Human-gating the export or recording the export action in the audit log.
- Any new dedicated page or REST endpoint for the export (the trigger is the in-chat tool).
- Pagination, streaming, or large-log performance work beyond a straightforward full dump.

## Scope

### In scope

- A new export module (`app/audit_export.py`) with `audit_to_csv()` and `audit_to_xlsx()` over the existing audit rows.
- A new in-chat **READ** tool that returns both encoded files.
- Extending the chat SSE `download` field to carry **a list** of files so two download buttons render in one turn.
- A round-trip test covering both formats.

### Out of scope

- Export filtering / search (Non-goal).
- Confirm-gating or self-auditing the export (Non-goal).
- A standalone audit-log viewer page or `/audit/export` HTTP endpoint (Non-goal).

## Proposed Design

### New services / components

- **`app/audit_export.py`** — formatting functions mirroring `app/batch.py`'s `results_to_csv()`:
  - `audit_to_csv(rows) -> str`
  - `audit_to_xlsx(rows) -> bytes` (via **openpyxl**)
- **New READ tool** in `agent/tools.py` (e.g. `export_audit_log`) that reads the audit rows (via `agent/audit.py`) and returns both formats base64-encoded for download. Registered in `READ_TOOLS` (not gated).
- **System-prompt line** in `agent/llm.py` routing "export the audit log" requests to the new tool.

### Existing code touched

- `agent/audit.py` — a read accessor for all rows (extend `recent()` or add a full-dump helper) if one isn't already suitable.
- `app/agent_chat.py` — extend the `download` SSE field / `_download()` to support **multiple** files (a list) rather than a single descriptor.
- `app/static/chat-widget.js` and `app/static/agent.js` — render a download button per file in the list (reusing the existing `renderDownload` helper in a loop).
- `agent/tools.py`, `agent/llm.py` — register the tool and its routing line.

### Data model changes

- None. Read-only over the existing audit table; no schema change, no migration.

### External dependencies

- **openpyxl** (new) for .xlsx generation.

## Open questions

- Who specifically needs the export, and is there an external compliance/recordkeeping requirement driving it (affects required columns and formatting)?
- Should column headers / ordering match a particular reporting template, or is the raw audit-row shape acceptable?
- Is filtering (date range / actor) needed soon enough to design the tool's signature for it now, even though it's deferred?
- For the .xlsx, are any niceties expected (frozen header row, column widths, typed timestamp cells), or is a plain sheet sufficient for the first cut?

## References

- Prior art in this repo: `app/batch.py` `results_to_csv()` + the batch results-CSV download (SSE `download` field, `renderDownload` in the chat JS).
- `agent/audit.py` — the append-only audit log this exports.
