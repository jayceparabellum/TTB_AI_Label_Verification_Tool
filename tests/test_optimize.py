"""Tests for the generic optimization harness (eval/optimize.py) and its concrete
RAG refuse-threshold application (eval/optimize_rag_thresholds.py).

The harness tests use a synthetic, deterministic metric_fn — no LLM, no network.
The RAG application test runs fully offline (BM25-only, no model constructed) and
asserts the shipped 0.50/0.80 config is among the top feasible configs.
"""

from __future__ import annotations

from eval.optimize import MetricResult, format_report, optimize


# --------------------------------------------------------------------------- #
# Generic harness                                                             #
# --------------------------------------------------------------------------- #

def test_finds_the_max():
    """A simple unimodal score is maximized over the grid."""
    sweep = optimize(lambda p: float(-(p["x"] - 3) ** 2), {"x": [0, 1, 2, 3, 4, 5]})
    assert sweep.best is not None
    assert sweep.best.params == {"x": 3}
    assert sweep.best.score == 0.0
    # Ranked best-first.
    assert [c.params["x"] for c in sweep.candidates][0] == 3


def test_minimize():
    """maximize=False selects the lowest score."""
    sweep = optimize(lambda p: float((p["x"] - 2) ** 2), {"x": [0, 1, 2, 3, 4]},
                     maximize=False)
    assert sweep.best.params == {"x": 2}
    assert sweep.best.score == 0.0


def test_feasibility_beats_score():
    """An infeasible higher-score candidate loses to a feasible lower one."""
    def metric(p):
        x = p["x"]
        # x=10 has the best raw score but is infeasible; x=4 is the best feasible.
        return MetricResult(score=float(x), feasible=(x <= 4))

    sweep = optimize(metric, {"x": [1, 2, 4, 10]})
    assert sweep.best.params == {"x": 4}        # not 10, despite 10 scoring higher
    assert sweep.best.score == 4.0
    # Infeasible candidates still appear in the ranking, but below all feasible ones.
    assert sweep.candidates[-1].params == {"x": 10}
    assert not sweep.candidates[-1].feasible
    assert all(c.feasible for c in sweep.feasible)


def test_no_feasible_candidate():
    """When nothing satisfies the constraint, best is None."""
    sweep = optimize(lambda p: MetricResult(score=float(p["x"]), feasible=False),
                     {"x": [1, 2, 3]})
    assert sweep.best is None
    assert sweep.feasible == ()
    assert len(sweep.candidates) == 3           # all still measured + ranked


def test_handles_ties_deterministically():
    """Equal scores produce a stable, deterministic ordering (no crash, repeatable)."""
    grid = {"x": [1, 2, 3], "y": ["a", "b"]}
    s1 = optimize(lambda p: 5.0, grid)          # every candidate scores the same
    s2 = optimize(lambda p: 5.0, grid)
    assert s1.best is not None
    order1 = [c.params for c in s1.candidates]
    order2 = [c.params for c in s2.candidates]
    assert order1 == order2                      # deterministic across runs
    assert len(order1) == 6                       # full Cartesian product


def test_cartesian_product_and_memoization():
    """The full product is swept; identical param signatures are measured once."""
    calls = []

    def metric(p):
        calls.append(dict(p))
        return float(p["a"] + p["b"])

    sweep = optimize(metric, {"a": [1, 2], "b": [10, 20, 30]})
    assert len(sweep.candidates) == 6            # 2 x 3
    assert len(calls) == 6                         # each distinct combo once
    assert sweep.best.params == {"a": 2, "b": 30}


def test_empty_grid():
    """An empty grid yields no candidates and no best."""
    sweep = optimize(lambda p: 1.0, {})
    assert sweep.candidates == ()
    assert sweep.best is None
    assert "Empty grid" in format_report(sweep)


def test_bare_float_treated_as_feasible():
    """A metric_fn returning a plain number is treated as a feasible candidate."""
    sweep = optimize(lambda p: float(p["x"]), {"x": [1, 2, 3]})
    assert sweep.best.params == {"x": 3}
    assert all(c.feasible for c in sweep.candidates)


def test_report_renders_table():
    """format_report renders a ranked markdown table with detail columns + best mark."""
    def metric(p):
        return MetricResult(score=float(p["x"]), feasible=(p["x"] != 2),
                            detail={"note": f"x={p['x']}"})

    report = format_report(optimize(metric, {"x": [1, 2, 3]}), title="My Sweep")
    assert "# My Sweep" in report
    assert "| rank |" in report
    assert "note" in report                       # detail column present
    assert "✅" in report                          # best feasible marked
    assert "Best feasible config:" in report


# --------------------------------------------------------------------------- #
# Concrete application: RAG refuse-threshold tuning (offline)                 #
# --------------------------------------------------------------------------- #

def test_rag_threshold_sweep_offline(monkeypatch):
    """The RAG-threshold application runs offline and returns a feasible best config
    whose off-corpus refusal fraction is >= the shipped (0.50/0.80) config's; the
    chosen config keeps golden at 100%. Asserts NO LLM is constructed during the
    sweep."""
    import eval.optimize_rag_thresholds as ort

    # Fail loudly if anything tries to build a model during the sweep.
    import agent.llm as agent_llm

    def _no_llm(*a, **k):                          # pragma: no cover - only if violated
        raise AssertionError("LLM must not be constructed during the offline sweep")

    monkeypatch.setattr(agent_llm, "make_llm", _no_llm, raising=False)

    sweep = ort.run_sweep()
    assert sweep.best is not None, "expected at least one feasible config"

    # The shipped config must be present and feasible.
    shipped = ort.shipped_candidate(sweep)
    assert shipped is not None
    assert shipped.feasible, "shipped 0.50/0.80 config must stay feasible"

    # The best is at least as good as shipped on the off-corpus refusal objective.
    assert sweep.best.score >= shipped.score

    # Golden stays 100% at the chosen config (encoded in feasibility + detail).
    assert sweep.best.result.detail["golden_answered"] == ort.N_GOLDEN_INCORPUS
    assert sweep.best.result.detail["golden_refused"] == ort.N_GOLDEN_OUTCORPUS

    # The shipped config is among the TOP feasible configs (tied at the best score).
    top_feasible_scores = {c.score for c in sweep.feasible}
    assert shipped.score == max(top_feasible_scores)


def test_rag_threshold_report_mentions_shipped():
    """The rendered report flags the shipped config row."""
    import eval.optimize_rag_thresholds as ort

    sweep = ort.run_sweep()
    report = format_report(sweep, title="RAG Refuse-Threshold Sweep")
    # Shipped params appear in the table.
    assert "0.5" in report and "0.8" in report
    assert "Best feasible config:" in report
