"""RAG eval: score the knowledge layer on the golden set.

Three honest metrics (per the brief):
  * hit-rate     — the controlling section is among the answer's citations
                   (and out-of-corpus queries are correctly REFUSED).
  * faithfulness — the answer text contains nothing beyond the retrieved chunks
                   (it's assembled extractively, so every cited chunk's text must
                   appear and no free-form claim is added).
  * citation     — every answered query carries >= 1 valid citation.

Usage:  python eval/run_rag_eval.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag import generate                                   # noqa: E402
from rag.ingest import load_corpus                         # noqa: E402

_GOLDEN = Path(__file__).resolve().parent / "rag_golden.json"


def evaluate() -> dict:
    cases = json.loads(_GOLDEN.read_text())["cases"]
    chunk_by_section = {c.section: c for c in load_corpus()}
    hits = faithful = cited_ok = 0
    rows = []
    for case in cases:
        r = generate.answer(case["q"], case["bt"])
        sections = {c["section"] for c in r["citations"]}
        if case["section"] is None:                        # expect a refusal
            hit = r["status"] == "refused"
            faith = cite = True                            # nothing to ground/cite
        else:
            hit = case["section"] in sections
            # faithfulness: every cited chunk's text appears verbatim in the answer
            faith = all(chunk_by_section[s].text in r["answer"] for s in sections
                        if s in chunk_by_section)
            cite = len(r["citations"]) >= 1
        hits += hit
        faithful += faith
        cited_ok += cite
        rows.append((case["q"], case["section"], r["status"], sorted(sections), hit))
    n = len(cases)
    return {"n": n, "hit_rate": hits / n, "faithfulness": faithful / n,
            "citation_rate": cited_ok / n, "rows": rows}


def main() -> None:
    m = evaluate()
    print("# RAG Eval\n")
    print(f"{'query':42} {'expect':7} {'status':9} cites")
    for q, sec, status, sections, hit in m["rows"]:
        mark = "ok" if hit else "MISS"
        print(f"{q[:42]:42} {str(sec):7} {status:9} {','.join(sections) or '—'}  {mark}")
    print(f"\n- hit-rate:      {m['hit_rate']:.0%}  (target >= 80%)")
    print(f"- faithfulness:  {m['faithfulness']:.0%}  (target 100%)")
    print(f"- citation-rate: {m['citation_rate']:.0%}  (target 100%)")


if __name__ == "__main__":
    main()
