// Vanilla-JS chat client: POST a message, stream SSE events, render the visible
// tool-step trail + the assistant's text. On a 'confirm' event (a write the agent
// proposed), show Approve / Cancel; the human decision resumes the same run.
// No framework, no build step.
(function () {
  const log = document.getElementById("chat-log");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const imageField = document.getElementById("chat-image");
  const send = document.getElementById("chat-send");

  // One thread per page load -> session memory ("that one") persists across turns.
  const threadId = (window.crypto && crypto.randomUUID)
    ? crypto.randomUUID() : "t-" + Date.now() + "-" + Math.floor(Math.random() * 1e6);

  function bubble(kind, text) {
    const el = document.createElement("div");
    el.className = "msg msg-" + kind;
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  function confirmCard(summary) {
    const card = document.createElement("div");
    card.className = "msg msg-confirm";
    const p = document.createElement("p");
    p.textContent = "Approve this action? " + (summary || "");
    const row = document.createElement("div");
    row.className = "confirm-actions";
    const yes = document.createElement("button");
    yes.className = "btn-primary"; yes.textContent = "Approve";
    const no = document.createElement("button");
    no.className = "btn-secondary"; no.textContent = "Cancel";
    row.appendChild(yes); row.appendChild(no);
    card.appendChild(p); card.appendChild(row);
    log.appendChild(card);
    log.scrollTop = log.scrollHeight;
    yes.addEventListener("click", function () { card.remove(); resume("approve"); });
    no.addEventListener("click", function () { card.remove(); resume("cancel"); });
  }

  async function streamResponse(resp) {
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
        if (evt.type === "tool_call") bubble("tool", "🔧 calling " + evt.tool + "…");
        else if (evt.type === "tool_step") bubble("tool", "🔧 " + evt.tool + " → " + evt.result);
        else if (evt.type === "message") bubble("assistant", evt.text);
        else if (evt.type === "error") bubble("error", evt.text);
        else if (evt.type === "confirm") confirmCard(evt.summary);
      }
    }
  }

  async function post(url, fields) {
    send.disabled = true;
    try {
      const resp = await fetch(url, { method: "POST", body: new URLSearchParams(fields) });
      await streamResponse(resp);
    } catch (e) {
      bubble("error", "Couldn't reach the assistant. The button verifier still works.");
    } finally {
      send.disabled = false;
    }
  }

  function ask(message, imageId) {
    bubble("user", message);
    post("/agent/chat", { message: message, image_id: imageId || "", thread_id: threadId });
  }

  function resume(decision) {
    bubble("user", decision === "approve" ? "✓ Approved" : "✗ Cancelled");
    post("/agent/resume", { thread_id: threadId, decision: decision });
  }

  document.querySelectorAll(".chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      input.value = chip.textContent;
      imageField.value = chip.dataset.image || "";
      input.focus();
    });
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    const imageId = imageField.value;
    input.value = ""; imageField.value = "";
    ask(message, imageId);
  });
})();
