"""Render the append-only audit log as downloadable CSV / Excel.

Read-only formatting over the rows returned by `agent.audit.all_rows()` — mirrors
the style of `app.batch.results_to_csv()`: stateless, exception-free over the rows
it is given, and the single source of truth for the export's column shape so the
CSV and the XLSX always carry identical data in identical order.
"""

from __future__ import annotations

import csv
import io

from openpyxl import Workbook

# The export column order: the row id, then who/what/when/why exactly as recorded.
# Kept here (not imported from audit) so the export's shape is explicit and stable
# even if the audit schema gains columns later.
COLUMNS = ["id", "ts", "actor", "action", "target_result_id",
           "old_verdict", "new_verdict", "reason"]


def _cell(row: dict, col: str) -> str:
    """One cell, with None rendered as an empty string (CSV/XLSX have no null)."""
    val = row.get(col)
    return "" if val is None else str(val)


def audit_to_csv(rows) -> str:
    """Render audit rows as a CSV string for download (header + one row each)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow([_cell(row, c) for c in COLUMNS])
    return buf.getvalue()


def audit_to_xlsx(rows) -> bytes:
    """Render audit rows as a single-sheet .xlsx workbook (header + one row each).

    A plain sheet — no styling/typed cells (deferred; see PRD open questions). Values
    are written as strings so the XLSX round-trips byte-for-byte against the CSV.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "audit_log"
    ws.append(COLUMNS)
    for row in rows:
        ws.append([_cell(row, c) for c in COLUMNS])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
