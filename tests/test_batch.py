"""Batch core: CSV parsing, join matrix, cap, summary, CSV export."""

from pathlib import Path

import pytest

from app import batch
from app.batch import BATCH_MAX_LABELS, CsvFormatError, parse_csv, results_to_csv, run_batch

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(),
    reason="sample images not generated (run scripts/generate_samples.py)",
)


def _img(name):
    return (f"{name}.png", (SAMPLES / f"{name}.png").read_bytes())


def _csv(*rows, header="filename,brand,alcohol_content"):
    return ("\n".join([header, *rows])).encode()


# --- parse_csv ----------------------------------------------------------------
def test_parse_csv_basic():
    rows, dups = parse_csv(_csv("a.png,Acme,5.0"))
    assert rows["a.png"].brand == "Acme"
    assert rows["a.png"].alcohol_content == "5.0"
    assert dups == set()


def test_parse_csv_bom_and_whitespace_and_case():
    raw = "﻿FileName, Brand , Alcohol_Content\n A.PNG , Acme , 5.0 \n".encode()
    rows, _ = parse_csv(raw)
    assert "a.png" in rows
    assert rows["a.png"].brand == "Acme"


def test_parse_csv_missing_column_raises():
    with pytest.raises(CsvFormatError):
        parse_csv(b"filename,brand\na.png,Acme\n")


def test_parse_csv_duplicate_filename_recorded():
    rows, dups = parse_csv(_csv("a.png,Acme,5.0", "a.png,Other,9.0"))
    assert "a.png" in dups
    assert "a.png" not in rows          # never silently picks a row (D2)


# --- run_batch ----------------------------------------------------------------
def test_run_batch_happy_statuses():
    images = [_img("clean_pass"), _img("abv_mismatch"), _img("bad_warning")]
    csv = _csv(
        "clean_pass.png,Stone's Throw,5.0",
        "abv_mismatch.png,Stone's Throw,5.0",
        "bad_warning.png,Stone's Throw,5.0",
    )
    res = run_batch(images, csv)
    by = {r.filename: r.status for r in res.rows}
    assert by["clean_pass.png"] == "pass"
    assert by["abv_mismatch.png"] == "flag"
    assert by["bad_warning.png"] == "flag"
    assert res.summary["passed"] == 1
    assert res.summary["flagged"] == 2
    assert res.summary["total"] == 3


def test_run_batch_image_without_row():
    res = run_batch([_img("clean_pass")], _csv("other.png,X,5"))
    assert res.rows[0].status == "no_application_data"


def test_run_batch_row_without_image():
    res = run_batch([_img("clean_pass")],
                    _csv("clean_pass.png,Stone's Throw,5.0", "ghost.png,X,5"))
    statuses = {r.filename: r.status for r in res.rows}
    assert statuses["ghost.png"] == "no_image"


def test_run_batch_duplicate_filename_is_error_row():
    res = run_batch([_img("clean_pass")],
                    _csv("clean_pass.png,A,5", "clean_pass.png,B,9"))
    assert res.rows[0].status == "duplicate_application_data"
    assert res.summary["errors"] == 1


def test_run_batch_unreadable_image():
    res = run_batch([("junk.png", b"not an image")], _csv("junk.png,X,5"))
    assert res.rows[0].status == "unreadable"


def test_run_batch_malformed_csv():
    res = run_batch([_img("clean_pass")], b"nonsense without columns\n")
    assert res.error
    assert not res.rows


def test_run_batch_over_cap():
    images = [_img("clean_pass") for _ in range(BATCH_MAX_LABELS + 1)]
    res = run_batch(images, _csv("clean_pass.png,X,5"))
    assert res.capped is True
    assert res.error
    assert not res.rows          # capped before any OCR


def test_summary_matches_row_tally():
    images = [_img("clean_pass"), _img("abv_mismatch")]
    res = run_batch(images, _csv("clean_pass.png,Stone's Throw,5.0",
                                 "abv_mismatch.png,Stone's Throw,5.0"))
    counts = res.summary
    assert counts["passed"] + counts["flagged"] + counts["needs_review"] + counts["errors"] == counts["total"]


# --- results_to_csv (U3) ------------------------------------------------------
def test_results_to_csv_round_trips_through_parse():
    res = run_batch([_img("clean_pass")], _csv("clean_pass.png,Stone's Throw,5.0"))
    out = results_to_csv(res)
    assert out.splitlines()[0] == ("filename,overall,brand,alcohol_content,"
                                   "government_warning,net_contents,class_type")
    assert "clean_pass.png" in out


def test_batch_adjudicates_optional_columns_when_present():
    res = run_batch(
        [_img("clean_pass")],
        _csv("clean_pass.png,Stone's Throw,5.0,750 mL,Stone's Throw",
             header="filename,brand,alcohol_content,net_contents,class_type"))
    names = [f.field for f in res.rows[0].fields]
    assert "net_contents" in names and "class_type" in names


def test_batch_skips_optional_columns_when_absent():
    res = run_batch([_img("clean_pass")], _csv("clean_pass.png,Stone's Throw,5.0"))
    assert [f.field for f in res.rows[0].fields] == \
        ["brand", "alcohol_content", "government_warning"]


def test_static_template_parses():
    template = Path(__file__).resolve().parent.parent / "app" / "static" / "batch-template.csv"
    rows, _ = parse_csv(template.read_bytes())
    assert rows  # the shipped template is a valid mapping
