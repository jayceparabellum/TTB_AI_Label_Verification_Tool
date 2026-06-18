// Global pop-out assistant. Same SSE backend as the /chat page, but rendered as a
// minimizable panel docked bottom-right of every page. State (open/closed, thread
// id, transcript) lives in sessionStorage so the conversation survives navigation
// across the server-rendered pages and clears when the tab closes. No build step.
(function () {
  const root = document.getElementById("cw-root");
  if (!root) return;
  const panel = document.getElementById("cw-panel");
  const log = document.getElementById("cw-log");
  const form = document.getElementById("cw-form");
  const input = document.getElementById("cw-input");
  const imageField = document.getElementById("cw-image");
  const send = document.getElementById("cw-send");
  const launcher = document.getElementById("cw-launcher");

  const K_STATE = "cw-state";        // "open" | "closed"
  const K_THREAD = "cw-thread";      // stable thread id -> server-side memory continuity
  const K_LOG = "cw-log";            // JSON array of {kind, text}

  function newThread() {
    return (window.crypto && crypto.randomUUID)
      ? crypto.randomUUID() : "t-" + Date.now() + "-" + Math.floor(Math.random() * 1e6);
  }

  let threadId = sessionStorage.getItem(K_THREAD);
  if (!threadId) { threadId = newThread(); sessionStorage.setItem(K_THREAD, threadId); }

  function loadLog() {
    try { return JSON.parse(sessionStorage.getItem(K_LOG) || "[]"); } catch (e) { return []; }
  }
  let messages = loadLog();
  function saveLog() { sessionStorage.setItem(K_LOG, JSON.stringify(messages)); }

  // --- rendering -------------------------------------------------------------
  function renderBubble(kind, text) {
    const el = document.createElement("div");
    el.className = "msg msg-" + kind;
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  function renderConfirm(summary) {
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
    yes.addEventListener("click", function () {
      card.remove(); dropConfirm(); resume("approve");
    });
    no.addEventListener("click", function () {
      card.remove(); dropConfirm(); resume("cancel");
    });
  }

  // Persisted bubble (survives navigation). Confirm cards are persisted too so a
  // paused write can still be approved after a page change (thread is server-side).
  function pushMsg(kind, text) {
    messages.push({ kind: kind, text: text }); saveLog();
    if (kind === "confirm") renderConfirm(text); else renderBubble(kind, text);
  }
  function dropConfirm() {
    messages = messages.filter(function (m) { return m.kind !== "confirm"; }); saveLog();
  }

  function replay() {
    log.innerHTML = "";
    messages.forEach(function (m) {
      if (m.kind === "confirm") renderConfirm(m.text); else renderBubble(m.kind, m.text);
    });
  }

  // --- SSE plumbing (mirrors agent.js) --------------------------------------
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
        if (evt.type === "tool_call") pushMsg("tool", "🔧 calling " + evt.tool + "…");
        else if (evt.type === "tool_step") pushMsg("tool", "🔧 " + evt.tool + " → " + evt.result);
        else if (evt.type === "message") pushMsg("assistant", evt.text);
        else if (evt.type === "error") pushMsg("error", evt.text);
        else if (evt.type === "confirm") pushMsg("confirm", evt.summary);
      }
    }
  }

  async function post(url, fields) {
    send.disabled = true;
    try {
      const resp = await fetch(url, { method: "POST", body: new URLSearchParams(fields) });
      await streamResponse(resp);
    } catch (e) {
      pushMsg("error", "Couldn't reach the assistant. The button verifier still works.");
    } finally {
      send.disabled = false;
    }
  }

  function ask(message, imageId) {
    pushMsg("user", message);
    post("/agent/chat", { message: message, image_id: imageId || "", thread_id: threadId });
  }

  function resume(decision) {
    pushMsg("user", decision === "approve" ? "✓ Approved" : "✗ Cancelled");
    post("/agent/resume", { thread_id: threadId, decision: decision });
  }

  // --- open / minimize / close ----------------------------------------------
  function setState(state) {
    root.setAttribute("data-state", state);
    sessionStorage.setItem(K_STATE, state);
    if (state === "open") setTimeout(function () { input.focus(); }, 60);
  }

  launcher.addEventListener("click", function () { setState("open"); });
  document.getElementById("cw-min").addEventListener("click", function () { setState("closed"); });
  document.getElementById("cw-close").addEventListener("click", function () {
    // Close clears the conversation and starts a fresh thread next time.
    messages = []; saveLog(); replay();
    threadId = newThread(); sessionStorage.setItem(K_THREAD, threadId);
    setState("closed");
  });

  // Esc closes (keeps the conversation).
  panel.addEventListener("keydown", function (e) {
    if (e.key === "Escape") setState("closed");
  });

  document.querySelectorAll(".cw-chip").forEach(function (chip) {
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

  // --- restore on load -------------------------------------------------------
  replay();
  setState(sessionStorage.getItem(K_STATE) === "open" ? "open" : "closed");
})();
