"""U3 — SSE chat web layer: page renders, stream emits tool steps + text, button
UI is untouched, and a missing model degrades gracefully (never a 500)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

import app.agent_chat as agent_chat
from app.agent_chat import STORE
from app.main import app

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(),
    reason="sample images not generated",
)
client = TestClient(app)


class _StubModel:
    def invoke(self, messages):
        if any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(content="The label passed all three checks.")
        return AIMessage(content="", tool_calls=[{
            "name": "verify_label",
            "args": {"brand": "Stone's Throw", "alcohol_content": "5.0"},
            "id": "c1", "type": "tool_call"}])


def test_chat_page_renders_with_chips_and_nav():
    html = client.get("/chat").text
    assert 'id="chat-log"' in html and "/static/agent.js" in html
    assert "chip" in html and 'href="/chat"' in html       # prompt chips + nav link


def test_agent_chat_streams_tool_step_and_final(monkeypatch):
    STORE.seed_samples()
    monkeypatch.setattr(agent_chat, "make_llm", lambda *a, **k: _StubModel())
    body = client.post("/agent/chat",
                       data={"message": "verify the clean pass sample",
                             "image_id": "clean_pass"}).text
    assert "tool_step" in body and "verify_label" in body   # visible tool step
    assert "PASS" in body                                   # deterministic verdict surfaced
    assert '"type": "message"' in body                      # model narration
    assert '"type": "done"' in body


def test_button_ui_unchanged_regression():
    assert client.get("/").status_code == 200               # home still works
    r = client.post("/verify-sample/clean_pass")
    assert "PASS &mdash; everything matches" in r.text       # core path untouched


def test_model_offline_degrades_gracefully():
    # No stub + no running Ollama -> the model invoke fails; the stream must emit a
    # friendly error event and finish 200, never a 500/stack trace.
    r = client.post("/agent/chat", data={"message": "hello", "image_id": ""})
    assert r.status_code == 200
    assert '"type": "error"' in r.text and "offline" in r.text.lower()
    assert '"type": "done"' in r.text
