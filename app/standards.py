"""Standards-of-identity recognition for class/type designations (27 CFR Parts 4 & 5).

Answers one question, offline and deterministically: **is a claimed class/type
designation a recognized standard of identity, and under which citation?** It is
*membership* against the curated `rag/corpus/class_type_designations.json` dataset —
NOT compositional rule enforcement (aging, mash bill, proof floors). A recognized
designation can support a deterministic PASS; an unrecognized one defers to human
review with the controlling citation. It never asserts a designation is *invalid*.

Matching is **whole-token containment**: a claim is recognized when it contains a known
designation/alias as a contiguous run of tokens — so "Kentucky Straight Bourbon Whiskey"
matches "bourbon", while "Virginia" never matches "gin" (token equality, never naive
substring). This is the exact discipline that keeps short designations from matching on
incidental overlap (cf. the class/type presence fix in app/matching.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .matching import normalize_loose

_DATASET = Path(__file__).resolve().parent.parent / "rag" / "corpus" / "class_type_designations.json"


@dataclass(frozen=True)
class Recognition:
    """Outcome of recognize(). `citation` is {section, source_url} when recognized."""
    recognized: bool
    beverage_type: str | None
    citation: dict | None
    message: str


@dataclass(frozen=True)
class Composition:
    """Outcome of check_composition() — an ADVISORY-only ABV/proof floor-and-ceiling
    check for a recognized class/type. `status` is "OK" (in range, or no rule/ABV to
    check) or "REVIEW" (claimed ABV outside the class's cited range). It is NEVER a
    confident FAIL/reject (zero-confident-wrong; KTD2): an out-of-range ABV defers to a
    human with the controlling citation, never an auto-rejection. `checked` is False
    when the check was a no-op (designation unrecognized, no claimed ABV, or no cited
    ABV bound for the class) — a no-op never adds a flag. `citation` is the controlling
    {section, source_url} when a bound was checked, else None."""
    status: str                  # "OK" | "REVIEW"
    checked: bool
    citation: dict | None
    message: str


@dataclass(frozen=True)
class _Entry:
    designation: str
    beverage_type: str
    section: str
    source_url: str
    phrases: tuple[tuple[str, ...], ...]   # normalized token tuples (designation + aliases)
    abv_min: float | None                  # cited ABV floor (percent ABV), or None
    abv_max: float | None                  # cited ABV ceiling (percent ABV), or None
    comp_section: str                      # controlling ABV section (may differ from `section`)


@lru_cache(maxsize=1)
def _entries() -> tuple[_Entry, ...]:
    raw = json.loads(_DATASET.read_text())["designations"]
    out: list[_Entry] = []
    for e in raw:
        names = [e["designation"], *e.get("aliases", [])]
        phrases = tuple(tuple(normalize_loose(n).split()) for n in names if normalize_loose(n))
        out.append(_Entry(e["designation"], e["beverage_type"], e["section"],
                          e["source_url"], phrases,
                          e.get("abv_min"), e.get("abv_max"),
                          e.get("composition_section") or e["section"]))
    return tuple(out)


def _contains(claim_tokens: list[str], phrase: tuple[str, ...]) -> bool:
    """True when `phrase` appears as a contiguous run of whole tokens in claim_tokens."""
    n, m = len(claim_tokens), len(phrase)
    if m == 0 or m > n:
        return False
    return any(tuple(claim_tokens[i:i + m]) == phrase for i in range(n - m + 1))


def _resolve(designation: str, beverage_type: str | None):
    """Resolve `designation` to its single most-specific recognized entry, or to a
    reason it can't be resolved. Returns (entry, None) on success, else (None, message).
    Shared by recognize() and check_composition() so the two can never drift on which
    entry a claim maps to (and thus which citation/rule applies)."""
    claim_tokens = normalize_loose(designation or "").split()
    if not claim_tokens:
        return None, "No class/type designation was provided."

    # (specificity, entry) for every entry with a whole-token phrase match.
    matches: list[tuple[int, _Entry]] = []
    for entry in _entries():
        best = max((len(p) for p in entry.phrases if _contains(claim_tokens, p)), default=0)
        if best:
            matches.append((best, entry))

    if beverage_type:
        matches = [m for m in matches if m[1].beverage_type == beverage_type]

    if not matches:
        return None, (
            f"'{designation}' is not a recognized 27 CFR class/type designation — "
            "recommend human review against the standards of identity.")

    btypes = {e.beverage_type for _, e in matches}
    if len(btypes) > 1 and not beverage_type:
        return None, (
            f"'{designation}' is ambiguous across beverage types — recommend human review.")

    # Most specific (longest-phrase) match supplies the citation/rule.
    return max(matches, key=lambda m: m[0])[1], None


def recognize(designation: str, beverage_type: str | None = None) -> Recognition:
    """Is `designation` a recognized 27 CFR class/type? Optionally constrained to a
    beverage type. Returns a Recognition with the controlling citation when recognized."""
    entry, reason = _resolve(designation, beverage_type)
    if entry is None:
        return Recognition(False, None, None, reason)
    return Recognition(
        True, entry.beverage_type,
        {"section": entry.section, "source_url": entry.source_url},
        f"'{designation}' is a recognized {entry.beverage_type} class/type "
        f"(27 CFR §{entry.section}).")


def check_composition(designation: str, abv: float | None,
                      beverage_type: str | None = None) -> Composition:
    """ADVISORY ABV/proof floor-and-ceiling check for a recognized class/type.

    Compares the claimed `abv` (percent ABV — the value app/matching.py already parsed,
    proof understood as 2x ABV) against the cited ABV envelope for the recognized class
    (e.g. distilled spirits at not less than 40% ABV / 80 proof under 27 CFR §5.143;
    table wine not over 14% ABV and dessert wine 14-24% ABV under §4.21). Purely data +
    Python — no LLM, fully offline, like recognize().

    Strictly additive and never confident-wrong (HARD INVARIANT 1 + KTD2): an out-of-range
    ABV returns status "REVIEW" with the controlling citation and a plain-language
    recommendation to verify — NEVER a FAIL/reject. The check is a silent no-op
    (checked=False, status="OK") when there is nothing to assess: the designation is
    unrecognized, no ABV was claimed, or the recognized class carries no cited ABV bound.
    A no-op adds no flag (HARD INVARIANT 2)."""
    entry, _reason = _resolve(designation, beverage_type)
    if entry is None or abv is None or (entry.abv_min is None and entry.abv_max is None):
        return Composition("OK", False, None, "")

    citation = {"section": entry.comp_section, "source_url": entry.source_url}
    below = entry.abv_min is not None and abv < entry.abv_min
    above = entry.abv_max is not None and abv > entry.abv_max
    if below or above:
        rng = _range_text(entry.abv_min, entry.abv_max)
        return Composition(
            "REVIEW", True, citation,
            f"the claimed {abv:g}% ABV is outside the typical {rng} for "
            f"'{entry.designation}' under 27 CFR §{entry.comp_section}; please verify. "
            "This is advisory; it is never an auto-rejection.")
    return Composition(
        "OK", True, citation,
        f"the claimed {abv:g}% ABV is within the typical "
        f"{_range_text(entry.abv_min, entry.abv_max)} for '{entry.designation}' "
        f"(27 CFR §{entry.comp_section}).")


def _range_text(abv_min: float | None, abv_max: float | None) -> str:
    """Human-readable ABV envelope, e.g. 'range of not less than 40% ABV',
    'range of not over 14% ABV', or 'range of 14-24% ABV'."""
    if abv_min is not None and abv_max is not None:
        return f"range of {abv_min:g}-{abv_max:g}% ABV"
    if abv_min is not None:
        return f"range of not less than {abv_min:g}% ABV"
    return f"range of not over {abv_max:g}% ABV"
