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
  const attachBtn = document.getElementById("chat-attach");
  const fileInput = document.getElementById("chat-file");
  const attachments = document.getElementById("chat-attachments");

  // One thread per page load -> session memory ("that one") persists across turns.
  const threadId = (window.crypto && crypto.randomUUID)
    ? crypto.randomUUID() : "t-" + Date.now() + "-" + Math.floor(Math.random() * 1e6);

  let attached = null;   // {id, name} of an uploaded image in focus (per page)

  function bubble(kind, text) {
    const el = document.createElement("div");
    el.className = "msg msg-" + kind;
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  // Clickable "Verify this label" suggestion after an upload (rendered live).
  function renderSuggest(text, fill) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "chip chat-suggest";
    b.textContent = text;
    b.addEventListener("click", function () {
      input.value = fill; input.focus(); b.remove();
    });
    log.appendChild(b);
    log.scrollTop = log.scrollHeight;
  }

  // Batch results-CSV download button (rendered live; not persisted).
  function downloadMime(filename) {
    return /\.xlsx$/i.test(filename || "")
      ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      : "text/csv";
  }
  function renderDownload(dl) {
    const name = dl.filename || "batch_results.csv";
    const a = document.createElement("a");
    a.className = "btn-secondary chat-download";
    a.textContent = "⬇ Download " + name;
    a.download = name;
    a.href = "data:" + downloadMime(name) + ";base64," + dl.b64;
    log.appendChild(a);
    log.scrollTop = log.scrollHeight;
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
        else if (evt.type === "tool_step") {
          bubble("tool", "🔧 " + evt.tool + " → " + evt.result);
          if (evt.download && evt.download.b64) renderDownload(evt.download);
          if (Array.isArray(evt.downloads)) evt.downloads.forEach(function (dl) {
            if (dl && dl.b64) renderDownload(dl);
          });
        }
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

  // --- attachments / image upload -------------------------------------------
  function renderAttachment() {
    attachments.innerHTML = "";
    if (!attached) return;
    const chip = document.createElement("span");
    chip.className = "chat-attachment";
    chip.appendChild(document.createTextNode("🖼 " + attached.name));
    const x = document.createElement("button");
    x.type = "button"; x.className = "chat-attachment-x";
    x.setAttribute("aria-label", "Remove attached image"); x.textContent = "✕";
    x.addEventListener("click", function () { attached = null; renderAttachment(); });
    chip.appendChild(x);
    attachments.appendChild(chip);
  }

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
          attached = { id: it.id, name: it.name }; renderAttachment();
          bubble("tool", "🖼 Attached " + it.name + ".");
          renderSuggest("Verify this label", "Verify this label");
        } else if (it.kind === "csv") {
          bubble("tool", "📎 " + it.name + " (" + it.rows + " row" + (it.rows === 1 ? "" : "s") +
                         ") staged — drop the matching images, then say “verify all of these”.");
        } else if (it.kind === "zip") {
          bubble("tool", "📦 " + it.name + " — " + it.extracted + " label" +
                         (it.extracted === 1 ? "" : "s") + " unzipped and staged. " +
                         "Add the CSV (if you haven't), then say “verify all of these”.");
        } else if (it.kind === "rejected") {
          bubble("error", it.name + ": " + it.reason);
        }
      });
    } catch (e) {
      bubble("error", "Upload failed. The button verifier still works.");
    } finally {
      send.disabled = false;
    }
  }

  attachBtn.addEventListener("click", function () { fileInput.click(); });
  fileInput.addEventListener("change", function () { uploadFiles(fileInput.files); fileInput.value = ""; });
  ["dragenter", "dragover"].forEach(function (ev) {
    log.addEventListener(ev, function (e) { e.preventDefault(); log.classList.add("drag"); });
  });
  log.addEventListener("dragleave", function (e) { if (!log.contains(e.relatedTarget)) log.classList.remove("drag"); });
  log.addEventListener("drop", function (e) {
    e.preventDefault(); log.classList.remove("drag");
    if (e.dataTransfer && e.dataTransfer.files) uploadFiles(e.dataTransfer.files);
  });
  // paste an image straight from the clipboard (e.g. a screenshot of a label)
  document.addEventListener("paste", function (e) {
    const items = (e.clipboardData && e.clipboardData.items) || [];
    const files = [];
    for (let i = 0; i < items.length; i++) {
      if (items[i].kind === "file") { const f = items[i].getAsFile(); if (f) files.push(f); }
    }
    if (files.length) { e.preventDefault(); uploadFiles(files); }
  });

  document.querySelectorAll(".chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      input.value = chip.textContent;
      imageField.value = chip.dataset.image || "";
      attached = null; renderAttachment();         // a sample chip replaces any upload
      input.focus();
    });
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    // An uploaded image takes precedence over a sample chip selection.
    const imageId = attached ? attached.id : imageField.value;
    input.value = ""; imageField.value = "";
    ask(message, imageId);
  });
})();
