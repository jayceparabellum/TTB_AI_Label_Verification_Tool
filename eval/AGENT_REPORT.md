# Agent Behavior Eval Report

Replays the committed agent snapshots and grades the load-bearing invariants **deterministically** (no LLM, no credits): the agent reports the deterministic tool's verdict **verbatim**, routes to the right tool, never runs a WRITE without the confirm gate firing, and RAG **cites-or-refuses**. Judge scores are baked in at record time and threshold-checked here. `record` (live, spends credits) refreshes the snapshots; this `gate` is the free, CI-safe path.

| case | verbatim | routing | confirm-gate | cite/refuse | judge | result |
|------|------|------|------|------|------|------|
| batch_verify_gated | — | ✅ | ✅ | — | ✅ | ✅ PASS |
| explain_flag_warning_caps | — | ✅ | — | ✅ | — | ✅ PASS |
| regulatory_lookup_cited | — | ✅ | — | ✅ | — | ✅ PASS |
| verify_label_flag | ✅ | ✅ | — | — | ✅ | ✅ PASS |
| verify_label_pass | ✅ | ✅ | — | — | ✅ | ✅ PASS |
| verify_text_pass | ✅ | ✅ | — | — | ✅ | ✅ PASS |

- **Cases passing:** 6/6 = **100.0%** → **PASS** (all invariants hold)
