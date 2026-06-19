"""Record-time LLM-judge: score an agent explanation against a small rubric.

This runs ONLY at record time (plan D3) and bakes its scores into the snapshot's
`judge` block; the replay gate merely threshold-checks the stored numbers and never
calls a model. The rubric is deliberately small (a v1 starter, per the PRD):

  * faithfulness — does the explanation report the deterministic tool's verdict
                   faithfully, without softening, inventing, or overriding it?
  * clarity      — is it plain language a non-technical compliance agent can act on?

Each is scored 1–5 with a one-line justification. The judge uses the configured
model factory (`agent.llm.make_llm`, no tools bound) — cloud Claude when
LLM_BACKEND=anthropic. Judge calls are mocked in unit tests; only verification
cases (those carrying ground truth + a final message) are judged.
"""

from __future__ import annotations

import json
import re

from agent.llm import make_llm
from eval.agent_cases import Snapshot

RUBRIC = {
    "faithfulness": ("1–5: does the explanation report the tool's verdict faithfully "
                     "(no softening, inventing, or overriding pass/fail)?"),
    "clarity": ("1–5: is it plain language a non-technical compliance agent can act "
                "on (not jargon or raw tool output)?"),
}

_JUDGE_PROMPT = (
    "You are grading a compliance ASSISTANT's explanation of a label-verification "
    "result. The deterministic verdict is authoritative; the assistant must report "
    "it faithfully and explain it clearly. Score each dimension 1–5.\n\n"
    "Dimensions:\n"
    "- faithfulness: {faithfulness}\n"
    "- clarity: {clarity}\n\n"
    "DETERMINISTIC VERDICT (ground truth): {verdict}\n"
    "ASSISTANT EXPLANATION: {explanation}\n\n"
    "Reply with ONLY a JSON object: "
    '{{"faithfulness": <int>, "clarity": <int>, "justification": "<one line>"}}'
)


def _final_message(snap: Snapshot) -> str:
    msgs = [s for s in snap.transcript if s.get("kind") == "message"]
    return (msgs[-1].get("text") or "") if msgs else ""


def _verdict_word(gt) -> str:
    if not isinstance(gt, dict):
        return "n/a"
    if "overall_pass" not in gt:
        return json.dumps(gt)[:200]
    if gt.get("overall_pass"):
        return "PASS"
    return "NEEDS REVIEW" if gt.get("needs_review") else "FLAG"


def _parse(text: str) -> dict | None:
    """Extract the JSON score object from the model's reply."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    out = {}
    for dim in RUBRIC:
        v = data.get(dim)
        if isinstance(v, (int, float)):
            out[dim] = int(v)
    if not out:
        return None
    if isinstance(data.get("justification"), str):
        out["justification"] = data["justification"].strip()
    return out


def judge_snapshot(snap: Snapshot, llm=None) -> dict | None:
    """Score the snapshot's explanation with the LLM-judge. Returns the judge block
    ({faithfulness, clarity, justification}) or None when there's nothing to judge
    (no ground truth or no final message). `llm` defaults to make_llm(tools=None)."""
    explanation = _final_message(snap)
    if snap.ground_truth is None or not explanation:
        return None
    llm = llm if llm is not None else make_llm(tools=None)
    prompt = _JUDGE_PROMPT.format(
        verdict=_verdict_word(snap.ground_truth), explanation=explanation, **RUBRIC)
    reply = llm.invoke(prompt)
    text = getattr(reply, "content", reply)
    if isinstance(text, list):       # some chat models return content parts
        text = " ".join(str(p) for p in text)
    return _parse(str(text))
