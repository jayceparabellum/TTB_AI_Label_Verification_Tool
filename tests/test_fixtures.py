"""The brief's label-fixture matrix: 5 core cases + a genuine brand-mismatch and a
one-word-wrong warning, each asserting the expected per-field outcome, plus the
< 5 s latency bound. Text-based cases use reverify_text (matchers on known text) so
the expected outcome is deterministic and not OCR-dependent."""

from pathlib import Path

import pytest

from app.reference import OFFICIAL_GOVERNMENT_WARNING
from app.verify import reverify_text, verify_label

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(), reason="sample images not generated")


def _png(name):
    return (SAMPLES / f"{name}.png").read_bytes()


def _verdicts(result):
    return result.verdicts          # the {field: passed} map now lives on the model


# --- Image fixtures -----------------------------------------------------------
def test_fixture_all_pass():
    r = verify_label(_png("clean_pass"), brand="Stone's Throw", alcohol_content="5.0")
    assert r.overall_pass and all(_verdicts(r).values())


def test_fixture_fuzzy_brand_passes_on_case_and_punctuation():
    r = verify_label(_png("clean_pass"), brand="STONES THROW", alcohol_content="5.0")
    assert _verdicts(r)["brand"] is True          # fuzzy ignores case/punctuation


def test_fixture_title_case_warning_fails():
    r = verify_label(_png("bad_warning"), brand="Stone's Throw", alcohol_content="5.0")
    assert _verdicts(r)["government_warning"] is False


def test_fixture_abv_mismatch_flags():
    r = verify_label(_png("abv_mismatch"), brand="Stone's Throw", alcohol_content="5.0")
    assert _verdicts(r)["alcohol_content"] is False


def test_fixture_genuine_brand_mismatch_fails():
    r = verify_label(_png("clean_pass"), brand="Totally Different Co", alcohol_content="5.0")
    assert _verdicts(r)["brand"] is False


# --- Text fixtures (deterministic, not OCR-dependent) -------------------------
def test_fixture_missing_warning_does_not_pass():
    r = reverify_text("Stone's Throw\nALC 5.0% BY VOL\n12 FL OZ",
                      brand="Stone's Throw", alcohol_content="5.0")
    assert _verdicts(r)["government_warning"] is False


def test_fixture_one_word_wrong_warning_fails():
    wrong = OFFICIAL_GOVERNMENT_WARNING.replace("birth defects", "birth defects and harm")
    r = reverify_text(f"Stone's Throw\nALC 5.0% BY VOL\n{wrong}",
                      brand="Stone's Throw", alcohol_content="5.0")
    assert _verdicts(r)["government_warning"] is False


# --- Latency bound ------------------------------------------------------------
def test_every_verify_under_5s_including_cold_start():
    for name in ("clean_pass", "abv_mismatch", "bad_warning"):
        r = verify_label(_png(name), brand="Stone's Throw", alcohol_content="5.0")
        assert r.elapsed_ms < 5000, f"{name} took {r.elapsed_ms} ms"
