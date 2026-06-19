"""Generic, dependency-free optimization harness over the eval backbone.

The "iterate" half of the measure->iterate loop (PRD 0002 / the ce-optimize
pattern): given a metric function and a small parameter grid, sweep the full
Cartesian product, score each candidate, and keep the best — subject to a hard
feasibility constraint (e.g. "golden hit-rate must stay 100%").

Pure and deterministic: this module makes NO LLM calls, NO network requests, and
spends NO credits. It is a measurement tool. The metric function it drives is
responsible for staying offline too (the RAG application in
``optimize_rag_thresholds.py`` does).

Design:
  * ``optimize(metric_fn, grid, *, maximize=True)`` sweeps ``grid`` (param-name ->
    list of candidate values), calls ``metric_fn(params)`` for each combo, and
    returns a :class:`Sweep`: the ranked candidates plus the best FEASIBLE one.
  * ``metric_fn`` returns a :class:`MetricResult` (``score``, ``feasible``,
    ``detail``) or a bare ``float`` (treated as feasible). The optimizer maximizes
    (or minimizes) ``score`` subject to ``feasible`` — an infeasible candidate
    never wins over a feasible one, regardless of score.
  * ``format_report(sweep)`` renders a ranked markdown table mirroring the style of
    ``eval/run_eval.py``'s report.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class MetricResult:
    """The outcome of scoring one candidate configuration.

    ``score`` is the (sortable) secondary objective; ``feasible`` is the hard
    constraint gate — an infeasible candidate is never selected as best, however
    high its score. ``detail`` carries arbitrary measurement context for the report.
    """

    score: float
    feasible: bool = True
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Candidate:
    """One evaluated point in the grid: its params and its metric result."""

    params: dict[str, Any]
    result: MetricResult

    @property
    def score(self) -> float:
        return self.result.score

    @property
    def feasible(self) -> bool:
        return self.result.feasible


@dataclass(frozen=True)
class Sweep:
    """The full ranked sweep plus the best feasible candidate (None if none)."""

    candidates: tuple[Candidate, ...]      # ranked best-first (feasible outrank infeasible)
    best: Candidate | None                 # best FEASIBLE candidate, or None
    maximize: bool

    @property
    def feasible(self) -> tuple[Candidate, ...]:
        return tuple(c for c in self.candidates if c.feasible)


def _coerce(out: MetricResult | float | int) -> MetricResult:
    if isinstance(out, MetricResult):
        return out
    if isinstance(out, (int, float)) and not isinstance(out, bool):
        return MetricResult(score=float(out))
    raise TypeError(
        f"metric_fn must return MetricResult or a number, got {type(out).__name__}")


def _grid_points(grid: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    """Full Cartesian product of the grid as a list of param dicts (stable order)."""
    if not grid:
        return []
    names = list(grid)
    return [dict(zip(names, combo)) for combo in itertools.product(*(grid[n] for n in names))]


def _sort_key(cand: Candidate, maximize: bool):
    # Feasible candidates always rank above infeasible ones; within each group,
    # order by score (descending if maximizing). Tie-break on a stable repr of the
    # params so equal-scoring candidates have a deterministic order.
    signed = cand.score if maximize else -cand.score
    return (cand.feasible, signed, _params_repr(cand.params))


def _params_repr(params: Mapping[str, Any]) -> str:
    return ",".join(f"{k}={params[k]}" for k in params)


def optimize(
    metric_fn: Callable[[dict[str, Any]], MetricResult | float],
    grid: Mapping[str, Sequence[Any]],
    *,
    maximize: bool = True,
) -> Sweep:
    """Sweep the full Cartesian product of ``grid`` and return the ranked results.

    ``metric_fn(params)`` is called once per grid point (memoized on the param
    signature, so a repeated point is not re-measured). The returned :class:`Sweep`
    ranks feasible candidates above infeasible ones, then by ``score`` (respecting
    ``maximize``); ``best`` is the top feasible candidate (None if none are feasible
    or the grid is empty).
    """
    cache: dict[str, MetricResult] = {}
    candidates: list[Candidate] = []
    for params in _grid_points(grid):
        key = _params_repr(params)
        if key not in cache:
            cache[key] = _coerce(metric_fn(params))
        candidates.append(Candidate(params=params, result=cache[key]))

    ranked = sorted(candidates, key=lambda c: _sort_key(c, maximize), reverse=True)
    feasible = [c for c in ranked if c.feasible]
    best = feasible[0] if feasible else None
    return Sweep(candidates=tuple(ranked), best=best, maximize=maximize)


def format_report(sweep: Sweep, *, title: str = "Optimization Sweep") -> str:
    """Render the ranked sweep as a markdown table (à la ``eval/run_eval.py``)."""
    lines = [f"# {title}", ""]
    if not sweep.candidates:
        lines += ["_Empty grid — no candidates to evaluate._", ""]
        return "\n".join(lines)

    goal = "maximize" if sweep.maximize else "minimize"
    lines += [f"**Objective:** {goal} score, subject to the feasibility constraint. "
              f"Feasible candidates rank above infeasible ones.", ""]

    # Stable union of detail keys (preserve first-seen order) for extra columns.
    detail_keys: list[str] = []
    for c in sweep.candidates:
        for k in c.result.detail:
            if k not in detail_keys:
                detail_keys.append(k)

    param_names = list(sweep.candidates[0].params)
    header = ["rank", *param_names, "score", "feasible", *detail_keys]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join("---" for _ in header) + "|")

    for rank, c in enumerate(sweep.candidates, start=1):
        best_mark = " ✅" if c is sweep.best else ""
        feas = ("yes" if c.feasible else "no") + (best_mark if c is sweep.best else "")
        row = [str(rank)]
        row += [_fmt(c.params[p]) for p in param_names]
        row += [_fmt(c.score), feas]
        row += [_fmt(c.result.detail.get(k, "")) for k in detail_keys]
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    if sweep.best is not None:
        lines.append(f"**Best feasible config:** {_params_repr(sweep.best.params)} "
                     f"(score {_fmt(sweep.best.score)}).")
    else:
        lines.append("**No feasible config found.**")
    lines.append("")
    return "\n".join(lines)


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))
    return str(v)
