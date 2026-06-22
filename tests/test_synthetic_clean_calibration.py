"""Calibration guard: the synthetic-clean cohort must never confidently FLAG.

These are diverse but genuinely-compliant rendered labels (full ALL-CAPS §16.21
warning, correct brand + ABV). The load-bearing invariant they protect is the
false-positive-rate goal: a compliant label may PASS or safely defer to NEEDS REVIEW
on a hard read, but it must NEVER receive a confident FLAG. A threshold change that
starts false-flagging clean labels fails here.
"""

from eval.run_eval import ROOT, _make_synthetic_clean
from app.verify import verify_label


def test_synthetic_clean_cohort_is_nonempty():
    assert len(_make_synthetic_clean()) >= 5      # diverse cohort, not a token sample


def test_synthetic_clean_never_confidently_flags():
    offenders = []
    for case in _make_synthetic_clean():
        r = verify_label((ROOT / case.image).read_bytes(),
                         brand=case.brand, alcohol_content=case.alcohol_content)
        assert r.readable, f"{case.name} should be readable"
        # Committed a confident verdict (not a deferral)? Then it must be PASS — a
        # confident FLAG on a compliant label is the false-positive defect.
        if not r.needs_review and not r.overall_pass:
            flagged = [f.field for f in r.fields if not f.passed and not f.inconclusive]
            offenders.append((case.name, flagged))
    assert not offenders, f"compliant labels confidently FLAGged: {offenders}"
