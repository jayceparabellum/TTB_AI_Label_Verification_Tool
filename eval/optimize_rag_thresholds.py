"""Concrete application of the optimization harness: RAG refuse-threshold tuning.

This AUTOMATES the calibration that was done by hand when the shipped thresholds
(``RAG_MIN_CONFIDENCE=0.50`` / ``RAG_DENSE_MIN_SIM=0.80``) were chosen. It sweeps
the threshold grid and, for each combo, measures the cite-or-refuse behavior over:

  * the golden set (``eval/rag_golden.json``) — in-corpus cases that must still
    ANSWER and out-of-corpus cases that must still REFUSE; and
  * a small held-out OFF-CORPUS probe set the golden set under-covers (Serving
    Facts panels, QR-code requirements, pictorial health warnings, the federal
    excise-tax rate) — these SHOULD all refuse.

Constraint (feasible): golden hit/refuse stays 100% (every in-corpus case answers,
every out-of-corpus case refuses).
Objective (maximize): fraction of the off-corpus probe set that refuses.

This is a MEASUREMENT tool, not a config change — it does NOT modify
``agent/config.py``. It runs fully OFFLINE: the refuse decision is retrieval-based
(BM25-only here, matching the CI/Render default — see ``tests/conftest.py``), and
``rag.generate.answer`` constructs no model on either the refuse or the answer path
(both only consult the retriever). Each combo monkeypatches
``agent.config.RAG_MIN_CONFIDENCE`` / ``RAG_DENSE_MIN_SIM``, runs the measurement,
and restores the originals in a ``finally`` so the sweep has no global side effects.

Run:  python eval/optimize_rag_thresholds.py
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.optimize import MetricResult, Sweep, format_report, optimize  # noqa: E402

# --- Grid (mirrors the manual calibration the shipped values came from) -------
MIN_CONFIDENCE_GRID = [0.3, 0.4, 0.5, 0.6]
DENSE_MIN_SIM_GRID = [0.55, 0.7, 0.8]

# The shipped config — must appear among the top feasible configs.
SHIPPED = {"RAG_MIN_CONFIDENCE": 0.50, "RAG_DENSE_MIN_SIM": 0.80}

# Held-out OFF-CORPUS probes the golden set under-covers; every one SHOULD refuse.
OFF_CORPUS_PROBES = [
    "Serving Facts panels on alcohol labels",
    "QR code requirements on labels",
    "pictorial health warnings on bottles",
    "federal excise tax rate",
]

_GOLDEN_PATH = Path(__file__).resolve().parent / "rag_golden.json"


def _load_golden() -> list[dict]:
    return json.loads(_GOLDEN_PATH.read_text())["cases"]


_GOLDEN = _load_golden()
N_GOLDEN_INCORPUS = sum(1 for c in _GOLDEN if c["section"] is not None)
N_GOLDEN_OUTCORPUS = sum(1 for c in _GOLDEN if c["section"] is None)
N_PROBES = len(OFF_CORPUS_PROBES)


@contextmanager
def _patched_thresholds(min_confidence: float, dense_min_sim: float):
    """Temporarily set the two RAG thresholds (BM25-only), restoring originals and
    resetting the retriever singleton so the sweep leaves no global side effects.

    ``RAG_DENSE`` is pinned "off" to match the CI/Render default (tests/conftest.py);
    the singleton is rebuilt under the pin and reset on exit so nothing leaks across
    combos or back into the rest of the process."""
    from agent import config
    import rag.retrieve as retrieve

    orig_mc = config.RAG_MIN_CONFIDENCE
    orig_ds = config.RAG_DENSE_MIN_SIM
    orig_dense = config.RAG_DENSE
    orig_retriever = retrieve._RETRIEVER
    try:
        config.RAG_MIN_CONFIDENCE = min_confidence
        config.RAG_DENSE_MIN_SIM = dense_min_sim
        config.RAG_DENSE = "off"
        retrieve._RETRIEVER = None              # rebuild BM25-only under the pin
        yield
    finally:
        config.RAG_MIN_CONFIDENCE = orig_mc
        config.RAG_DENSE_MIN_SIM = orig_ds
        config.RAG_DENSE = orig_dense
        retrieve._RETRIEVER = orig_retriever    # restore — no cross-combo leakage


def _measure(params: dict) -> MetricResult:
    """Score one threshold combo: feasible iff golden stays 100%; objective is the
    off-corpus probe refusal fraction. Uses only the status of each answer (the
    refuse path needs no model; the answer path constructs none either)."""
    mc = params["RAG_MIN_CONFIDENCE"]
    ds = params["RAG_DENSE_MIN_SIM"]
    with _patched_thresholds(mc, ds):
        from rag import generate

        golden_answered = golden_refused = 0
        for c in _GOLDEN:
            status = generate.answer(c["q"], c["bt"])["status"]
            if c["section"] is None:
                golden_refused += int(status == "refused")
            else:
                golden_answered += int(status == "answered")

        probe_refused = sum(
            generate.answer(p)["status"] == "refused" for p in OFF_CORPUS_PROBES)

    feasible = (golden_answered == N_GOLDEN_INCORPUS
                and golden_refused == N_GOLDEN_OUTCORPUS)
    score = probe_refused / N_PROBES if N_PROBES else 1.0
    return MetricResult(
        score=score,
        feasible=feasible,
        detail={
            "golden_answered": golden_answered,
            "golden_refused": golden_refused,
            "probe_refused": f"{probe_refused}/{N_PROBES}",
        },
    )


def run_sweep() -> Sweep:
    """Sweep the threshold grid offline and return the ranked :class:`Sweep`."""
    grid = {
        "RAG_MIN_CONFIDENCE": MIN_CONFIDENCE_GRID,
        "RAG_DENSE_MIN_SIM": DENSE_MIN_SIM_GRID,
    }
    return optimize(_measure, grid, maximize=True)


def shipped_candidate(sweep: Sweep):
    """The candidate in ``sweep`` matching the shipped config (or None)."""
    for c in sweep.candidates:
        if (c.params["RAG_MIN_CONFIDENCE"] == SHIPPED["RAG_MIN_CONFIDENCE"]
                and c.params["RAG_DENSE_MIN_SIM"] == SHIPPED["RAG_DENSE_MIN_SIM"]):
            return c
    return None


def main() -> None:
    sweep = run_sweep()
    print(format_report(sweep, title="RAG Refuse-Threshold Sweep"))
    shipped = shipped_candidate(sweep)
    if shipped is not None:
        rank = sweep.candidates.index(shipped) + 1
        print(f"_Shipped config (0.50 / 0.80): rank {rank}/{len(sweep.candidates)}, "
              f"feasible={shipped.feasible}, score={shipped.score:.3f} "
              f"(off-corpus refusal fraction)._")


if __name__ == "__main__":
    main()
