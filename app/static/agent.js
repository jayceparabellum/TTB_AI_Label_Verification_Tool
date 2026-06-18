// Minimal vanilla-JS chat client: POST a message, stream SSE events, render the
// visible tool-step trail + the assistant's text. No framework, no build step.
(function () {
  const log = document.getElementById("chat-log");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const imageField = document.getElementById("chat-image");
  const send = document.getElementById("chat-send");

  function bubble(kind, text) {
    const el = document.createElement("div");
    el.className = "msg msg-" + kind;
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  // Prompt chips fill the box and tag the sample image to verify.
  document.querySelectorAll(".chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      input.value = chip.textContent;
      imageField.value = chip.dataset.image || "";
      input.focus();
    });
  });

  async function ask(message, imageId) {
    bubble("user", message);
    send.disabled = true;
    const body = new URLSearchParams({ message: message, image_id: imageId || "" });
    let resp;
    try {
      resp = await fetch("/agent/chat", { method: "POST", body: body });
    } catch (e) {
      bubble("error", "Couldn't reach the assistant. The button verifier still works.");
      send.disabled = false;
      return;
    }
    // Parse the SSE stream incrementally.
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop();
      for (const part of parts) {
        const line = part.replace(/^data: /, "").trim();
        if (!line) continue;
        let evt;
        try { evt = JSON.parse(line); } catch (e) { continue; }
        if (evt.type === "tool_call") {
          bubble("tool", "🔧 calling " + evt.tool + "…");
        } else if (evt.type === "tool_step") {
          bubble("tool", "🔧 " + evt.tool + " → " + evt.result);
        } else if (evt.type === "message") {
          bubble("assistant", evt.text);
        } else if (evt.type === "error") {
          bubble("error", evt.text);
        }
      }
    }
    send.disabled = false;
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    const imageId = imageField.value;
    input.value = "";
    imageField.value = "";
    ask(message, imageId);
  });
})();
