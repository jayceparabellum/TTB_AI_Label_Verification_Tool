"""Batch verification: join N images to a CSV of claimed data, verify each.

Web-free and stateless. Reuses verify_label per label; every error path produces
a row (never an exception) so the web layer never 500s on bad input.

  CSV (filename,brand,alcohol_content) ─┐
                                        ├─ join by basename ─► verify_label ─► BatchRow
  N uploaded images ────────────────────┘                                         │
                                                          summary counts ◄─────────┘
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import List

from .matching import FieldResult
from .verify import verify_label

# Bounded synchronous batch: ~25 × ~0.7s ≈ ~18s on a 0.5-CPU host. Async/progress
# for the 200-300 target is deferred (see plan scope).
BATCH_MAX_LABELS = 25

REQUIRED_COLUMNS = {"filename", "brand", "alcohol_content"}


class CsvFormatError(Exception):
    """The CSV is unusable (empty or missing a required column)."""


@dataclass(frozen=True)
class ClaimedRow:
    brand: str
    alcohol_content: str


@dataclass
class BatchRow:
    filename: str
    # pass | flag | needs_review | unreadable | no_application_data |
    # no_image | duplicate_application_data
    status: str
    fields: List[FieldResult] = field(default_factory=list)
    message: str = ""

    @property
    def needs_attention(self) -> bool:
        return self.status != "pass"


@dataclass
class BatchResult:
    rows: List[BatchRow] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    capped: bool = False
    error: str = ""          # batch-level error (over cap, or bad CSV)


def parse_csv(data: bytes):
    """Parse the mapping CSV into (rows_by_filename, duplicate_filenames).

    Tolerant of a BOM, surrounding whitespace, and header casing. A filename that
    appears more than once is recorded as a duplicate and removed from the usable
    rows — the batch flags it rather than guessing which row to trust (D2).
    """
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise CsvFormatError("The CSV file appears to be empty.")
    columns = {(c or "").strip().lower() for c in reader.fieldnames}
    missing = REQUIRED_COLUMNS - columns
    if missing:
        raise CsvFormatError(
            "CSV is missing column(s): "
            + ", ".join(sorted(missing))
            + ". Expected a header row: filename, brand, alcohol_content."
        )

    rows: dict[str, ClaimedRow] = {}
    duplicates: set[str] = set()
    for raw in reader:
        norm = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        fn = norm.get("filename", "").lower()
        if not fn:
            continue
        if fn in rows or fn in duplicates:
            duplicates.add(fn)
            rows.pop(fn, None)
            continue
        rows[fn] = ClaimedRow(brand=norm.get("brand", ""),
                              alcohol_content=norm.get("alcohol_content", ""))
    return rows, duplicates


def _status_for(result) -> str:
    if not result.readable:
        return "unreadable"
    if result.needs_review:
        return "needs_review"
    return "pass" if result.overall_pass else "flag"


def _summarize(rows: List[BatchRow]) -> dict:
    summary = {"total": len(rows), "passed": 0, "flagged": 0,
               "needs_review": 0, "errors": 0}
    for row in rows:
        if row.status == "pass":
            summary["passed"] += 1
        elif row.status == "flag":
            summary["flagged"] += 1
        elif row.status == "needs_review":
            summary["needs_review"] += 1
        else:
            summary["errors"] += 1
    return summary


def run_batch(images: list[tuple[str, bytes]], csv_bytes: bytes,
              cap: int = BATCH_MAX_LABELS) -> BatchResult:
    """Verify each image against its CSV row. Returns a row per image + summary."""
    if len(images) > cap:
        return BatchResult(
            capped=True,
            error=(f"Batch is limited to {cap} labels at a time — you uploaded "
                   f"{len(images)}. Please split it into smaller batches."),
        )
    try:
        rows, duplicates = parse_csv(csv_bytes)
    except CsvFormatError as exc:
        return BatchResult(error=str(exc))

    out: list[BatchRow] = []
    seen: set[str] = set()
    for filename, data in images:
        key = filename.strip().lower()
        seen.add(key)
        if key in duplicates:
            out.append(BatchRow(filename, "duplicate_application_data",
                                message="This filename appears more than once in "
                                        "the CSV — fix the CSV and re-run."))
            continue
        claimed = rows.get(key)
        if claimed is None:
            out.append(BatchRow(filename, "no_application_data",
                                message="No CSV row matches this image's filename."))
            continue
        result = verify_label(data, brand=claimed.brand,
                              alcohol_content=claimed.alcohol_content)
        out.append(BatchRow(filename, _status_for(result),
                            fields=result.fields, message=result.message))

    # CSV entries (and unresolved duplicates) with no matching image.
    for fn in list(rows) + sorted(duplicates):
        if fn not in seen:
            status = ("duplicate_application_data" if fn in duplicates
                      else "no_image")
            msg = ("Duplicate filename in the CSV; no matching image uploaded."
                   if fn in duplicates else
                   "The CSV lists this filename but no matching image was uploaded.")
            out.append(BatchRow(fn, status, message=msg))

    return BatchResult(rows=out, summary=_summarize(out))


def results_to_csv(result: BatchResult) -> str:
    """Render a batch result as a CSV string for download (filename + verdicts)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["filename", "overall", "brand", "alcohol_content",
                     "government_warning"])
    for row in result.rows:
        verdicts = {f.field: ("PASS" if f.passed else "FLAG") for f in row.fields}
        writer.writerow([
            row.filename, row.status.upper(),
            verdicts.get("brand", ""),
            verdicts.get("alcohol_content", ""),
            verdicts.get("government_warning", ""),
        ])
    return buf.getvalue()
