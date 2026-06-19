# Agent Behavior Eval Report

Replays the committed agent snapshots and grades the load-bearing invariants **deterministically** (no LLM, no credits): the agent reports the deterministic tool's verdict **verbatim**, routes to the right tool, never runs a WRITE without the confirm gate firing, and RAG **cites-or-refuses**. Judge scores are baked in at record time and threshold-checked here. `record` (live, spends credits) refreshes the snapshots; this `gate` is the free, CI-safe path.

_No snapshots recorded yet._ Run `LLM_BACKEND=anthropic python eval/run_agent_eval.py record` to capture them (spends Anthropic credits), commit `eval/agent_snapshots/*.json`, then re-run the gate.

