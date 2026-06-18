"""Layer 3 — local RAG knowledge layer.

GROUNDS explanations and regulatory answers in the actual regulations; it gets NO
vote on any verdict. Every answer cites its controlling section and REFUSES when
retrieval is empty or weak ("not found in the regulations on file") — hallucinated
compliance text is the one failure mode that cannot ship. Runs fully offline over a
committed, citation-tagged corpus.
"""
