"""U3 — in-chat image verify: an uploaded image, referenced by the chat turn, yields
the SAME verdict the deterministic core gives on those bytes (button parity). The
stubbed model only triggers the tool; the verdict comes from the core, not the model."""

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

import app.agent_chat as agent_chat
from app.main import app
from app.verify import verify_label as core_verify

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "static" / "samples"
pytestmark = pytest.mark.skipif(
    not (SAMPLES / "clean_pass.png").exists(), reason="sample images not generated")
client = TestClient(app)


class _VerifyStub:
    """Emits a verify_label tool call, then a final summary once the tool returns."""

    def __init__(self, brand, abv):
        self.brand, self.abv = brand, abv

    def invoke(self, messages):
        if any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(content="Here is the result.")
        return AIMessage(content="", tool_calls=[{
            "name": "verify_label",
            "args": {"brand": self.brand, "alcohol_content": self.abv},
            "id": "c1", "type": "tool_call"}])


@pytest.mark.parametrize("sample,brand,abv,expect_pass", [
    ("clean_pass", "Stone's Throw", "5.0", True),
    ("bad_warning", "Stone's Throw", "5.0", False),   # title-case warning -> FLAG
])
def test_uploaded_image_verifies_with_button_parity(monkeypatch, sample, brand, abv, expect_pass):
    img = (SAMPLES / f"{sample}.png").read_bytes()
    tid = uuid.uuid4().hex
    # 1) upload the image in-chat -> get its session id
    up = client.post("/agent/upload", data={"thread_id": tid},
                     files=[("files", (f"{sample}.png", img, "image/png"))])
    image_id = up.json()["items"][0]["id"]
    # 2) a chat turn referencing that id verifies the UPLOADED bytes (not a sample)
    monkeypatch.setattr(agent_chat, "make_llm", lambda *a, **k: _VerifyStub(brand, abv))
    body = client.post("/agent/chat", data={
        "message": "verify this label", "image_id": image_id, "thread_id": tid}).text
    # 3) parity: the chat's verdict matches the core's verdict on the same bytes
    core = core_verify(img, brand=brand, alcohol_content=abv)
    assert core.overall_pass is expect_pass
    assert "tool_step" in body and "verify_label" in body
    assert ("PASS" if expect_pass else "FLAG") in body
