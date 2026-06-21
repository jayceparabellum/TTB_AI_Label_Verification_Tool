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
class _Entry:
    designation: str
    beverage_type: str
    section: str
    source_url: str
    phrases: tuple[tuple[str, ...], ...]   # normalized token tuples (designation + aliases)


@lru_cache(maxsize=1)
def _entries() -> tuple[_Entry, ...]:
    raw = json.loads(_DATASET.read_text())["designations"]
    out: list[_Entry] = []
    for e in raw:
        names = [e["designation"], *e.get("aliases", [])]
        phrases = tuple(tuple(normalize_loose(n).split()) for n in names if normalize_loose(n))
        out.append(_Entry(e["designation"], e["beverage_type"], e["section"],
                          e["source_url"], phrases))
    return tuple(out)


def _contains(claim_tokens: list[str], phrase: tuple[str, ...]) -> bool:
    """True when `phrase` appears as a contiguous run of whole tokens in claim_tokens."""
    n, m = len(claim_tokens), len(phrase)
    if m == 0 or m > n:
        return False
    return any(tuple(claim_tokens[i:i + m]) == phrase for i in range(n - m + 1))


def recognize(designation: str, beverage_type: str | None = None) -> Recognition:
    """Is `designation` a recognized 27 CFR class/type? Optionally constrained to a
    beverage type. Returns a Recognition with the controlling citation when recognized."""
    claim_tokens = normalize_loose(designation or "").split()
    if not claim_tokens:
        return Recognition(False, None, None, "No class/type designation was provided.")

    # (specificity, entry) for every entry with a whole-token phrase match.
    matches: list[tuple[int, _Entry]] = []
    for entry in _entries():
        best = max((len(p) for p in entry.phrases if _contains(claim_tokens, p)), default=0)
        if best:
            matches.append((best, entry))

    if beverage_type:
        matches = [m for m in matches if m[1].beverage_type == beverage_type]

    if not matches:
        return Recognition(
            False, None, None,
            f"'{designation}' is not a recognized 27 CFR class/type designation — "
            "recommend human review against the standards of identity.")

    btypes = {e.beverage_type for _, e in matches}
    if len(btypes) > 1 and not beverage_type:
        return Recognition(
            False, None, None,
            f"'{designation}' is ambiguous across beverage types — recommend human review.")

    # Most specific (longest-phrase) match supplies the citation.
    entry = max(matches, key=lambda m: m[0])[1]
    return Recognition(
        True, entry.beverage_type,
        {"section": entry.section, "source_url": entry.source_url},
        f"'{designation}' is a recognized {entry.beverage_type} class/type "
        f"(27 CFR §{entry.section}).")
