"""U3/U4 — SSE chat web layer: page renders, stream emits tool steps + text, the
button UI stays untouched, missing model degrades gracefully, and a proposed write
pauses for human approval over /agent/resume."""

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

import app.agent_chat as agent_chat
from agent import audit, config
from app.agent_chat import STORE
from app.main import app

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(),
    reason="sample images not generated",
)
client = TestClient(app)


class _ReadStub:
    def invoke(self, messages):
        if any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(content="The label passed all three checks.")
        return AIMessage(content="", tool_calls=[{
            "name": "verify_label",
            "args": {"brand": "Stone's Throw", "alcohol_content": "5.0"},
            "id": "c1", "type": "tool_call"}])


class _WriteStub:
    def invoke(self, messages):
        if any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(content="Done — the override is recorded.")
        return AIMessage(content="", tool_calls=[{
            "name": "override_result",
            "args": {"result_id": "r1", "new_status": "PASS",
                     "reason": "manual review confirms compliant"},
            "id": "w1", "type": "tool_call"}])


def _tid():
    return uuid.uuid4().hex


def test_chat_page_renders_with_chips_and_nav():
    html = client.get("/chat").text
    assert 'id="chat-log"' in html and "/static/agent.js" in html
    assert "chip" in html and 'href="/chat"' in html


def test_assistant_alias_serves_the_chat_page():
    # /assistant is an alias for /chat — same rendered page.
    assert client.get("/assistant").text == client.get("/chat").text


def test_popout_widget_on_every_page_except_chat():
    # The global pop-out assistant rides on every page (with the same prompt chips
    # + its client script) but is suppressed on the dedicated /chat page so there's
    # never a double chat UI.
    for path in ("/", "/text", "/batch"):
        html = client.get(path).text
        assert 'id="cw-root"' in html, f"{path}: widget missing"
        assert "/static/chat-widget.js" in html and 'class="cw-chip"' in html
    chat = client.get("/chat").text
    assert 'id="cw-root"' not in chat          # suppressed on the full /chat page


def test_agent_chat_streams_tool_step_and_final(monkeypatch):
    STORE.seed_samples()
    monkeypatch.setattr(agent_chat, "make_llm", lambda *a, **k: _ReadStub())
    body = client.post("/agent/chat", data={
        "message": "verify the clean pass sample", "image_id": "clean_pass",
        "thread_id": _tid()}).text
    assert "tool_step" in body and "verify_label" in body
    assert "PASS" in body and '"type": "message"' in body and '"type": "done"' in body


def test_button_ui_unchanged_regression():
    assert client.get("/").status_code == 200
    r = client.post("/verify-sample/clean_pass")
    assert "PASS &mdash; everything matches" in r.text


def test_model_offline_degrades_gracefully():
    r = client.post("/agent/chat", data={"message": "hello", "image_id": "",
                                         "thread_id": _tid()})
    assert r.status_code == 200
    assert '"type": "error"' in r.text and "offline" in r.text.lower()


def test_write_pauses_for_confirm_then_resume_approve_writes_audit(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_chat, "make_llm", lambda *a, **k: _WriteStub())
    monkeypatch.setattr(config, "AUDIT_DB", tmp_path / "audit.sqlite")
    tid = _tid()
    # 1) propose the write -> stream pauses with a confirm event, NO audit row yet.
    body = client.post("/agent/chat", data={"message": "override r1 to pass",
                                            "image_id": "", "thread_id": tid}).text
    assert '"type": "confirm"' in body and "Override" in body
    assert audit.recent() == []
    # 2) approve -> resume executes the write, exactly one audit row.
    body2 = client.post("/agent/resume", data={"thread_id": tid, "decision": "approve"}).text
    assert "tool_step" in body2 and "override" in body2.lower()
    assert len(audit.recent()) == 1 and audit.recent()[0]["new_verdict"] == "PASS"


def test_write_cancel_makes_no_change(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_chat, "make_llm", lambda *a, **k: _WriteStub())
    monkeypatch.setattr(config, "AUDIT_DB", tmp_path / "audit.sqlite")
    tid = _tid()
    client.post("/agent/chat", data={"message": "override r1", "image_id": "",
                                     "thread_id": tid})
    body = client.post("/agent/resume", data={"thread_id": tid, "decision": "cancel"}).text
    assert "cancelled" in body.lower()
    assert audit.recent() == []          # no write happened
