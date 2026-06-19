// Global pop-out assistant. Same SSE backend as the /chat page, but rendered as a
// minimizable panel docked bottom-right of every page. State (open/closed, thread
// id, transcript, attached image) lives in sessionStorage so the conversation
// survives navigation across the server-rendered pages and clears when the tab
// closes. Drop/pick a label image to verify it in-chat. No build step.
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
  const attachBtn = document.getElementById("cw-attach");
  const fileInput = document.getElementById("cw-file");
  const attachments = document.getElementById("cw-attachments");

  const K_STATE = "cw-state";        // "open" | "closed"
  const K_THREAD = "cw-thread";      // stable thread id -> server-side memory continuity
  const K_LOG = "cw-log";            // JSON array of {kind, text}
  const K_ATTACH = "cw-attached";    // {id, name} of the uploaded image in focus

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

  let attached = null;               // {id, name}
  try { attached = JSON.parse(sessionStorage.getItem(K_ATTACH) || "null"); } catch (e) { attached = null; }
  function saveAttach() {
    if (attached) sessionStorage.setItem(K_ATTACH, JSON.stringify(attached));
    else sessionStorage.removeItem(K_ATTACH);
  }

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
    yes.addEventListener("click", function () { card.remove(); dropConfirm(); resume("approve"); });
    no.addEventListener("click", function () { card.remove(); dropConfirm(); resume("cancel"); });
  }

  // A clickable "Verify this label" suggestion after an upload (rendered live, not
  // persisted): clicking pre-fills the box and focuses it so the user just adds the
  // claimed brand/ABV. The assistant still drives the verdict — this is only a nudge.
  function renderSuggest(text, fill) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "cw-chip cw-suggest";
    b.textContent = text;
    b.addEventListener("click", function () {
      input.value = fill; input.focus(); b.remove();
    });
    log.appendChild(b);
    log.scrollTop = log.scrollHeight;
  }

  // A batch results-CSV download button (rendered live; the blob is not persisted
  // to the transcript to keep sessionStorage small — re-run the batch to regenerate).
  function downloadMime(filename) {
    return /\.xlsx$/i.test(filename || "")
      ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      : "text/csv";
  }
  function renderDownload(dl) {
    const name = dl.filename || "batch_results.csv";
    const a = document.createElement("a");
    a.className = "btn-secondary cw-download";
    a.textContent = "⬇ Download " + name;
    a.download = name;
    a.href = "data:" + downloadMime(name) + ";base64," + dl.b64;
    log.appendChild(a);
    log.scrollTop = log.scrollHeight;
  }

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

  // --- attachments / image upload -------------------------------------------
  function renderAttachment() {
    attachments.innerHTML = "";
    if (!attached) return;
    const chip = document.createElement("span");
    chip.className = "cw-attachment";
    chip.appendChild(document.createTextNode("🖼 " + attached.name));
    const x = document.createElement("button");
    x.type = "button"; x.className = "cw-attachment-x";
    x.setAttribute("aria-label", "Remove attached image"); x.textContent = "✕";
    x.addEventListener("click", removeAttachment);
    chip.appendChild(x);
    attachments.appendChild(chip);
  }
  function removeAttachment() { attached = null; saveAttach(); renderAttachment(); }

  async function uploadFiles(fileList) {
    if (!fileList || !fileList.length) return;
    const fd = new FormData();
    fd.append("thread_id", threadId);
    for (let i = 0; i < fileList.length; i++) fd.append("files", fileList[i]);
    send.disabled = true;
    try {
      const resp = await fetch("/agent/upload", { method: "POST", body: fd });
      const data = await resp.json();
      (data.items || []).forEach(function (it) {
        if (it.kind === "image") {
          attached = { id: it.id, name: it.name }; saveAttach(); renderAttachment();
          pushMsg("tool", "🖼 Attached " + it.name + ".");
          renderSuggest("Verify this label", "Verify this label");
        } else if (it.kind === "csv") {
          pushMsg("tool", "📎 " + it.name + " (" + it.rows + " row" + (it.rows === 1 ? "" : "s") +
                          ") staged — drop the matching images, then say “verify all of these”.");
        } else if (it.kind === "zip") {
          pushMsg("tool", "📦 " + it.name + " — " + it.extracted + " label" +
                          (it.extracted === 1 ? "" : "s") + " unzipped and staged. " +
                          "Add the CSV (if you haven't), then say “verify all of these”.");
        } else if (it.kind === "rejected") {
          pushMsg("error", it.name + ": " + it.reason);
        }
      });
    } catch (e) {
      pushMsg("error", "Upload failed. The button verifier still works.");
    } finally {
      send.disabled = false;
    }
  }

  attachBtn.addEventListener("click", function () { fileInput.click(); });
  fileInput.addEventListener("change", function () { uploadFiles(fileInput.files); fileInput.value = ""; });

  // drag & drop onto the panel
  ["dragenter", "dragover"].forEach(function (ev) {
    panel.addEventListener(ev, function (e) { e.preventDefault(); root.classList.add("cw-dragging"); });
  });
  panel.addEventListener("dragleave", function (e) {
    if (!panel.contains(e.relatedTarget)) root.classList.remove("cw-dragging");
  });
  panel.addEventListener("drop", function (e) {
    e.preventDefault(); root.classList.remove("cw-dragging");
    if (e.dataTransfer && e.dataTransfer.files) uploadFiles(e.dataTransfer.files);
  });

  // paste an image straight from the clipboard (e.g. a screenshot of a label)
  panel.addEventListener("paste", function (e) {
    const items = (e.clipboardData && e.clipboardData.items) || [];
    const files = [];
    for (let i = 0; i < items.length; i++) {
      if (items[i].kind === "file") { const f = items[i].getAsFile(); if (f) files.push(f); }
    }
    if (files.length) { e.preventDefault(); uploadFiles(files); }
  });

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
        else if (evt.type === "tool_step") {
          pushMsg("tool", "🔧 " + evt.tool + " → " + evt.result);
          if (evt.download && evt.download.b64) renderDownload(evt.download);
          if (Array.isArray(evt.downloads)) evt.downloads.forEach(function (dl) {
            if (dl && dl.b64) renderDownload(dl);
          });
        }
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
    // Close clears the conversation, evicts any uploaded bytes, and starts fresh.
    messages = []; saveLog(); replay();
    removeAttachment();
    fetch("/agent/reset", { method: "POST", body: new URLSearchParams({ thread_id: threadId }) }).catch(function () {});
    threadId = newThread(); sessionStorage.setItem(K_THREAD, threadId);
    setState("closed");
  });

  panel.addEventListener("keydown", function (e) { if (e.key === "Escape") setState("closed"); });

  document.querySelectorAll(".cw-chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      input.value = chip.textContent;
      imageField.value = chip.dataset.image || "";
      removeAttachment();                 // a sample chip replaces any uploaded image
      input.focus();
    });
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    // An uploaded image (persisted) takes precedence over a sample chip selection.
    const imageId = attached ? attached.id : imageField.value;
    input.value = ""; imageField.value = "";
    ask(message, imageId);
  });

  // --- restore on load -------------------------------------------------------
  replay();
  renderAttachment();
  setState(sessionStorage.getItem(K_STATE) === "open" ? "open" : "closed");
})();
