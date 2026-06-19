---
title: "feat: Chatbox omni-ingest — image / text / CSV batch verification entirely in-chat"
status: planned
date: 2026-06-19
depth: deep
branch: feat/chatbox-omni-ingest
scope_source: PM scoping pass over the conversational-agent codebase (this session)
---

# feat: Chatbox omni-ingest — one-stop label verification inside the chat widget

## Summary

Make the pop-out chat widget a **one-stop ingestion surface**: a user can, without
leaving the chat, (a) **drag/drop or pick a label image** and have the AI verify
it, (b) **type/paste the label text** and have it verified, and (c) **upload a CSV
+ images for a batch run** — every existing page feature, orchestrated by the
assistant, in-chat.

The hard part is **not** the chat veneer — it is closing the ingestion gap: today
`verify_label` reads `active_image_id` from a STORE that only holds **seeded
samples**, and `/agent/chat` accepts **only form text fields** (no upload). This
plan adds (1) a companion **multipart upload endpoint** that stashes session bytes
in the STORE and returns ids the chat references, (2) **new/extended tools** that
verify an uploaded image, verify typed text, and run a batch from an uploaded CSV,
and (3) **frontend affordances** (drop zone / file picker / paste) wired into the
existing SSE + confirm-gate flow.

Every invariant holds unchanged: the **deterministic core owns every verdict**, the
**button UI stays primary**, **verification stays `<5 s`** (chat is off that path),
**every write is human-gated + audited**, and **nothing is persisted** beyond the
session STORE. The chat is strictly additive.

Build incrementally; the order below produces an independently demoable slice at
each step (image → text → batch → polish).

---

## Problem Frame

The conversational agent (Layer 2) and RAG (Layer 3) already ship
(`agent/`, `rag/`, the `cw-*` widget in `base.html`, `/agent/chat` + `/agent/resume`
SSE). But the chat can only verify the **bundled samples**: `STORE.seed_samples()`
loads sample PNGs by key, `verify_label` reads `state["active_image_id"]` from that
STORE, and the widget only sends `message` + a hidden `image_id` (pre-filled by a
prompt chip). A real user cannot get their **own** label into the chat.

The page features the chat must absorb:

| Page feature | Endpoint today | Core function | Chat equivalent (this plan) |
|---|---|---|---|
| Single image verify | `POST /verify` (multipart) | `verify_label(bytes, …)` | upload image → `verify_label` tool (existing, now fed real bytes) |
| Typed/pasted text verify | `POST /verify-text` (form) | `reverify_text(text, …)` | paste text → **new** `verify_text` tool |
| Batch CSV + images | `POST /batch` (multipart) | `run_batch(images, csv)` | upload CSV + images → **extended** `batch_verify` tool |
| Re-check edited values | `POST /reverify` | `reverify_text(…)` | already covered by `verify_text` / follow-up turns |
| Sample verify | `POST /verify-sample/{key}` | `verify_label` | already covered (seeded STORE) |

The four genuinely hard parts:

1. **Getting bytes into the chat flow.** The SSE turn is `application/x-www-form-urlencoded`;
   a file must arrive by a separate path and be referenced by id, OR the turn must
   become multipart. (Decision D1 below — recommend the **companion upload endpoint**.)
2. **Wiring uploads to tools without breaking button-parity or the STORE contract.**
   Tools must keep reading bytes from the STORE by id (never from model args), so
   the verdict stays deterministic and un-hallucinatable.
3. **Batch in chat** without busting the `<5 s` *verification* SLA framing or the
   25-label synchronous cap — and streaming the summary back as chat.
4. **Keeping every write human-gated.** A batch run is already a WRITE tool
   (`batch_verify` → confirm gate); user-uploaded batches must stay gated and the
   confirm summary must reflect the uploaded set, not the samples.

---

## Goals

- A user can drop/pick a label image **in the chat**, then ask "verify this" — and
  get the **same verdict the button would give** (`verify_label` parity).
- A user can paste label text **in the chat** and get it verified via `reverify_text`.
- A user can attach a **CSV + images** in the chat, approve the run, and watch the
  batch summary + flagged list stream back, with a downloadable results CSV.
- All of the above with **zero new pages**; the existing Single/Text/Batch pages stay
  primary and untouched.

### Non-goals

- The LLM/RAG ever deciding pass/fail, auto-approving, or auto-running a batch.
- Persisting uploads beyond the in-process session STORE (no disk, no PII at rest).
- Async/progress-bar batch beyond the existing **25-label synchronous cap**
  (`BATCH_MAX_LABELS`) — large-batch streaming is Later.
- Removing or bypassing the button UI; replacing the dedicated `/chat`, `/`, `/text`,
  `/batch` pages.
- Multi-image *single* verify, PDF ingestion, HEIC transcoding (inherits the core's
  `OcrReadError` "unreadable" path; documented limitation).

---

## Scope

### Must-have (the omni-ingest vertical)
- **M1** Companion upload endpoint(s) that stash session bytes in `STORE` and return ids.
- **M2** In-chat **image** drop/pick → `verify_label` on real uploaded bytes.
- **M3** In-chat **text** paste → new `verify_text` tool over `reverify_text`.
- **M4** In-chat **CSV + images batch** → extended `batch_verify` over `run_batch`,
  streamed summary + flagged list + results-CSV download, still confirm-gated.

### Should-have
- **S1** Attachment chips in the transcript ("📎 label.png", "📎 mapping.csv (12 rows)")
  and a "verify this" auto-suggest after an upload.
- **S2** Paste-an-image (clipboard) and paste-the-CSV-text affordances.
- **S3** Batch results CSV download surfaced as an in-chat link/button.
- **S4** Per-session STORE eviction / size guard (cap total bytes per thread).

### Later
- Async/progress batch for the 200–300 target; chunked multi-batch in chat.
- PDF / multi-page / HEIC ingestion.
- Re-using an uploaded image across turns by name ("verify the second one").

---

## UX Approach

One **attach affordance** added to the widget footer (and the `/chat` page form):
a paperclip button + a drop zone overlay over the whole panel + clipboard paste.
The same flow serves all three ingest types — the file's kind decides the path:

- **image/\*** → uploaded as the active image; chat suggests "Verify this label?"
- **.csv** → held as the pending batch mapping; chat asks for the images (or they're
  dropped together); on "verify all", the confirm gate fires.
- **typed text** → no upload; the user just pastes into the message box and says
  "verify this label text" (the assistant routes to `verify_text`).

```
┌─ Verification assistant ───────────────[–][✕]┐
│                                               │
│  user: (drops Sunny_Vale.png) ───────────────│
│  📎 Sunny_Vale.png  ·  ready                  │
│  assistant: Got the label. Verify it against  │
│             which brand and ABV?              │
│  user: Sunny Vale, 12.5%                      │
│  🔧 verify_label → PASS (96% confidence)      │
│  assistant: PASS. Brand, ABV, and the §16.21  │
│             warning all match.                │
│ ┌───────────────────────────────────────────┐ │
│ │   Drop a label, a CSV, or images here      │ │ ← drag overlay
│ └───────────────────────────────────────────┘ │
│ [📎] [ Ask the assistant…            ]   [▸]  │
│  Explanations only — every verdict comes from  │
│  the verifier, and you approve any change.     │
└───────────────────────────────────────────────┘
```

Batch flow (confirm-gated, summary streamed):

```
│  user: (drops mapping.csv + 12 images)        │
│  📎 mapping.csv (12 rows) · 12 images · ready │
│  user: verify all of these                    │
│  ┌─ Approve this action? ──────────────────┐  │
│  │ Run a batch over 12 uploaded labels      │  │
│  │            [ Approve ]   [ Cancel ]       │  │
│  └──────────────────────────────────────────┘ │
│  🔧 batch_verify → 12 total · 9 pass · 3 flag │
│  assistant: 9 passed, 3 flagged. Flagged:     │
│   • Cab_2021.png — ABV mismatch               │
│   • …          [ Download results CSV ]       │
```

Design conventions: large targets, plain language, reuses existing `cw-*` /`.msg-*`
/ `.btn-primary` styles and `Design.md` tokens. No build step.

---

## Architecture / Design

### Request flow (image ingest, the representative case)

```
Browser (chat-widget.js)                FastAPI                 STORE / agent
  drop image ──POST /agent/upload (multipart)──►  read bytes
                                                  STORE.put(bytes) → image_id ◄── per-thread
        ◄────────── {image_id, kind:"image"} ──────────
  send "verify this" + image_id ──POST /agent/chat (form, as today)──►
                                            stream_chat(msg, image_id, thread)
                                            state.active_image_id = image_id
                                            verify_label reads STORE[id]  ── deterministic core
        ◄──────── SSE tool_step / message / done ────────
```

### Backend changes (`app/main.py`, `app/agent_chat.py`)

- **New `POST /agent/upload` (multipart).** Accepts one or more `files` + `thread_id`.
  For each file: sniff kind by content-type/extension → `image/*`, `text/csv`/`.csv`,
  else reject with a friendly message. Stash bytes via `STORE.put(bytes)` (image) or
  a parallel **CSV/batch staging store** keyed by `thread_id` (see state changes).
  Return JSON `{items:[{kind, id, name, rows?}]}`. **No file touches disk.** Enforce a
  per-file and per-thread byte cap (Decision D3).
- **`/agent/chat` unchanged in shape** — it still takes `message` + `image_id` +
  `thread_id`. The upload endpoint feeds `image_id`; the CSV/images are referenced by
  `thread_id` from the staging store inside the batch tool (no model args).
  *(Alternative D1: make `/agent/chat` itself multipart. Rejected as default — it
  complicates the SSE generator and the resume path; a thin upload endpoint keeps the
  streaming turn simple and testable.)*
- `app/agent_chat.py`: `stream_chat` already forwards `image_id` into
  `state.active_image_id`; add `thread_id` into the graph input so batch/text tools
  can find the thread's staged CSV/images and so confirm summaries are accurate.

### New / extended tools (`agent/tools.py`)

- **`verify_label`** — *unchanged code*, now simply fed real uploaded bytes (the gap
  closes at the STORE/endpoint layer, not the tool). Parity is automatic.
- **`verify_text`** (NEW, READ tool) — wraps `app.verify.reverify_text(text, brand,
  alcohol_content, expected_warning)`. The pasted label text is supplied by the user
  turn (it *is* the label text — high confidence, same as `/verify-text`). Returns the
  verbatim `VerificationResult` fields, identical serialization to `run_verify`.
  Guard with `ocr.is_readable(text)` → friendly "paste the label text" message.
- **`batch_verify`** (EXTENDED, WRITE tool) — today runs over `_SAMPLES`. Extend to:
  if the thread has a **staged uploaded batch** (CSV + images), run `run_batch` over
  *that*; else fall back to the samples (preserves the existing demo chip). Reads the
  staged set from the thread store via injected state (never from model args). Sets
  `LAST_BATCH` so `list_flagged` works unchanged. Returns summary counts + a
  `results_csv_b64` so the client can offer a download.
- **`list_flagged`** — unchanged; already reads `LAST_BATCH`.

### State changes (`agent/state.py`, `agent/images.py`)

- `AgentState`: add `thread_id: Optional[str]` (so write-tool confirm summaries and
  the batch tool can locate the thread's staged batch). `active_image_id` already exists.
- `agent/images.py`: add a **per-thread batch staging store** — a dict
  `thread_id → {"csv": bytes, "images": list[(name, bytes)]}`. Same in-process,
  no-disk, no-PII contract as `ImageStore`; add a `clear(thread_id)` for the widget's
  Close button. Reuse `ImageStore` for image bytes (already keyed by uuid).

### Frontend changes (`app/static/chat-widget.js`, `agent.js`, `base.html`, `style.css`)

- `base.html`: add a paperclip `<button id="cw-attach">`, a hidden
  `<input type="file" id="cw-file" multiple accept="image/*,.csv">`, and a drop-overlay
  element inside `#cw-panel`. Mirror in `agent.html` for the `/chat` page.
- `chat-widget.js` (and the parallel `agent.js`):
  - dragover/drop on the panel → POST to `/agent/upload` with the files + `threadId`.
  - on response, render an attachment chip per item, store the returned `image_id`
    into the existing hidden `cw-image` field (image) or just note the staged batch.
  - support clipboard **paste** of an image (S2).
  - keep the existing SSE plumbing; add handling for a `download` event/field so the
    batch results CSV becomes a button.
  - the **Close** button additionally calls `/agent/upload`'s clear (or a tiny
    `/agent/reset`) to evict the thread's staged bytes (S4).
- `style.css`: extend `cw-*` with `.cw-attach`, `.cw-dropzone`, `.cw-attachment` chips
  (reuse existing tokens; no new design language).

### How each existing feature maps in

- **Single image** → `/agent/upload` (image) + `verify_label` (existing tool).
- **Text** → paste into the box + `verify_text` (new tool).
- **Batch** → `/agent/upload` (csv + images) + `batch_verify` (extended) +
  `list_flagged` + results-CSV download.
- **Re-check / sample** → already covered (follow-up turns / seeded STORE).

---

## Implementation Units (build order)

### U1 — Per-thread staging stores + state plumbing
**Goal:** A no-disk place to hold a thread's uploaded image bytes and staged batch,
plus `thread_id` in agent state.
**Files:** `agent/images.py` (add batch staging store + `clear`), `agent/state.py`
(add `thread_id`), `app/agent_chat.py` (thread `thread_id` into graph input),
`tests/test_agent_state_staging.py` (create).
**Approach:** Add `BATCH_STORE: dict[str, dict]` (or a small class) keyed by thread;
`put_batch(thread_id, csv, images)`, `get_batch`, `clear(thread_id)`. Keep
`ImageStore` for image bytes. Nothing persists to disk.
**Tests:** put/get/clear round-trips; `clear` evicts both image and batch entries for
a thread; state carries `thread_id`; no filesystem writes occur.

### U2 — `POST /agent/upload` multipart endpoint
**Goal:** Files reach the STORE and return referencable ids; nothing hits disk.
**Files:** `app/main.py` (route), `tests/test_agent_upload.py` (create).
**Approach:** `async def agent_upload(files: list[UploadFile], thread_id: str = Form)`.
Sniff each file: `image/*` → `STORE.put` → `{kind:"image", id, name}`; `.csv`/`text/csv`
→ stage into batch store (parse rows count via `batch.parse_csv` best-effort for the
chip label) → `{kind:"csv", name, rows}`; otherwise → `{kind:"rejected", name, reason}`.
Enforce per-file + per-thread byte caps (D3). Return `{items:[…]}`.
**Tests:** upload a PNG → STORE has the bytes under the returned id; upload a CSV →
batch store staged + row count; oversized/unknown type → friendly rejection, no 500;
upload + later `clear` evicts; multiple files in one request all stash.

### U3 — In-chat image verify (M2)
**Goal:** Drop/pick an image, say "verify this", get the button-parity verdict.
**Files:** `app/templates/base.html` + `agent.html` (attach button, file input, drop
overlay), `app/static/chat-widget.js` + `agent.js` (upload + chip + hidden image_id),
`app/static/style.css`, `tests/test_chat_image_ingest.py` (create).
**Approach:** Frontend posts dropped/picked images to `/agent/upload`, stores the
returned `image_id` in the existing hidden field, renders an attachment chip. The
existing `ask()` already sends `image_id` → `verify_label` reads it from the STORE.
**Tests (mostly backend/integration):** upload→chat round-trip yields a verdict equal
to `verify_label(bytes, …)` called directly (parity); a chat turn with a real uploaded
id flags a known-bad label exactly as the core does; widget renders an attachment chip
(DOM smoke if a JS test harness exists, else manual-verify note).

### U4 — `verify_text` tool + in-chat text verify (M3)
**Goal:** Paste label text, get it verified via `reverify_text`.
**Files:** `agent/tools.py` (add `verify_text`, register in `READ_TOOLS`/`ALL_TOOLS`),
`agent/llm.py` (one system-prompt line: "to verify pasted label TEXT, call
verify_text"), `tests/test_tool_verify_text.py` (create).
**Approach:** `verify_text(label_text, brand, alcohol_content, expected_warning="")`
→ `reverify_text(...)`, serialized identically to `run_verify`. `is_readable` guard.
No image needed; no STORE read.
**Tests:** parity with `reverify_text` on the same inputs; unreadable text → friendly
message not a verdict; the tool never emits a pass/fail of its own (verdict comes from
the core result); FLAG case (wrong ABV in text) matches the core.

### U5 — Uploaded-batch `batch_verify` + streamed results (M4)
**Goal:** Run a real uploaded CSV+images batch in-chat, confirm-gated, summary streamed,
results CSV downloadable.
**Files:** `agent/tools.py` (extend `batch_verify` to read the thread's staged batch
via injected state, fall back to samples), `agent/confirm.py` (`_summary` for
`batch_verify` reflects "N uploaded labels" vs samples), `app/agent_chat.py` (surface a
`results_csv_b64` as an SSE `download` field on the tool step), `app/static/chat-widget.js`
+ `agent.js` (render a download button), `tests/test_tool_batch_uploaded.py` (create).
**Approach:** `batch_verify(state)` → if `get_batch(state["thread_id"])` present, run
`run_batch(images, csv)` over it (respects `BATCH_MAX_LABELS` cap + all error rows);
else samples. Set `LAST_BATCH`. Return summary + `results_csv_b64`. Stays a WRITE tool →
confirm gate unchanged; summary now says how many labels.
**Tests:** staged batch runs over the uploaded set (not samples) and matches
`run_batch` directly (parity); confirm gate still pauses before the run; cancel → no run,
`LAST_BATCH` unchanged; over-cap upload → the core's "split it" error surfaces in chat,
no crash; `list_flagged` after an uploaded batch returns the uploaded flagged rows;
results CSV equals `results_to_csv(result)`.

### U6 — UX polish + session eviction (S1–S4)
**Goal:** Attachment chips, paste-image, download button, per-thread byte cap + Close eviction.
**Files:** `app/static/chat-widget.js` + `agent.js`, `app/static/style.css`,
`app/main.py` (optional `/agent/reset` or extend `/agent/upload` with a clear action),
`tests/test_chat_session_evict.py` (create).
**Approach:** Clipboard paste → upload; "Verify this label?" auto-suggest chip after an
image upload; download button from the `download` field; Close button evicts the thread's
staged bytes; enforce the per-thread cap from U2.
**Tests:** Close evicts image + batch stores for the thread; cap rejects an over-large
cumulative upload with a friendly message.

---

## Invariant-Preservation Notes

- **LLM never adjudicates.** Verdicts come only from `verify_label` / `verify_text`
  (→ `reverify_text`) / `batch_verify` (→ `run_batch`), serialized verbatim. Tools read
  bytes/CSV from the STORE by id/thread — **never** from model-supplied args — so the
  model can't substitute or hallucinate inputs or outcomes. System prompt unchanged in
  spirit (one routing line added).
- **`<5 s` verification.** The SLA is a property of the *deterministic verify path*,
  which is untouched (same `verify_label`/`reverify_text`/`run_batch`). The chat/LLM and
  the new upload endpoint are off that path. Batch keeps the **25-label synchronous cap**;
  no new latency on a single verify.
- **Human-gated writes.** `batch_verify` stays a WRITE tool behind `confirm_gate`'s
  `interrupt()`; the uploaded-batch run cannot start without explicit Approve. Override /
  manual-fallback are unchanged and still gated + audited. The agent can never auto-run.
- **Button UI primary / always available.** No page is removed or changed; `/`, `/text`,
  `/batch`, `/chat` keep working. Chat ingest is purely additive.
- **Offline by default.** Upload, STORE, OCR, matching, batch are all local; only the LLM
  uses cloud Claude when `LLM_BACKEND=anthropic`, which doesn't touch the deterministic
  contract. No new outbound calls.
- **No PII at rest.** Uploads live only in the in-process per-thread STORE; the Close
  button and per-thread cap evict them; nothing is written to disk.

---

## Risks, Open Questions & Decisions for the User

**Decisions the user must make:**

- **D1 — Upload transport.** *Recommended:* a **companion `POST /agent/upload`**
  (keeps the SSE turn simple, testable, and the resume path clean). *Alternative:* make
  `/agent/chat` itself multipart (fewer round-trips, but complicates streaming + resume).
- **D2 — Keep the separate Single/Text/Batch pages?** *Recommended:* **yes, keep them**
  (invariant: button UI stays primary). The chat is additive, not a replacement.
- **D3 — Upload caps.** Per-file size, per-thread cumulative size, and the **in-chat batch
  cap** (recommend reusing `BATCH_MAX_LABELS = 25`; larger batches → "use the Batch page"
  or split). Needs concrete numbers (e.g. 10 MB/file, 50 MB/thread).

**Other open questions:**

- File-type handling: images + `.csv` only? Reject PDF/HEIC with a friendly message
  (inherits the core's "unreadable" path) — confirm that's acceptable.
- Should an uploaded image auto-trigger a verify prompt, or always wait for the user to
  supply brand/ABV first? (Recommend: ask for the claimed values, never auto-verify.)
- Multi-image single-verify: out of scope here (one active image at a time) — confirm.
- Where to surface the batch **results CSV** download in a transcript that persists across
  navigation (sessionStorage) — link vs re-fetch.

---

## Test / Verification Strategy

- **Parity (the core guarantee):** for each ingest type, assert the chat path's verdict
  equals the core function called directly on the same bytes/text — `verify_label`,
  `reverify_text`, `run_batch` — on at least one PASS and one FLAG fixture each.
- **Upload endpoint:** image stashes to STORE; CSV stages + row count; oversized/unknown
  type → friendly rejection (no 500); no filesystem writes (socket/FS guard or temp-dir
  assertion).
- **HITL:** uploaded `batch_verify` still pauses at the confirm gate; Approve runs once;
  Cancel runs nothing and leaves `LAST_BATCH` unchanged.
- **Regression:** `/`, `/verify`, `/verify-text`, `/batch`, `/chat`, `/agent/chat`,
  `/agent/resume` all still pass (the additive change must not disturb them).
- **Session hygiene:** Close evicts the thread's staged bytes; per-thread cap enforced.
- **Manual demo (per slice):** drop an image → "verify this" → button-identical verdict;
  paste text → verdict; drop CSV+images → Approve → streamed summary + flagged + CSV
  download. Run with both `LLM_BACKEND` defaults (offline Ollama, cloud Claude).

---

## Sources & Research

- This codebase (read this session): `app/main.py`, `app/agent_chat.py`, `app/batch.py`,
  `app/verify.py`, `app/ocr.py`, `agent/tools.py`, `agent/images.py`, `agent/state.py`,
  `agent/graph.py`, `agent/confirm.py`, `agent/llm.py`,
  `app/static/chat-widget.js`, `app/static/agent.js`, `app/templates/base.html`,
  `app/static/style.css`.
- Prior plan: `docs/plans/2026-06-18-001-feat-conversational-agent-rag-plan.md`
  (the three-layer architecture + invariants this builds on).
- The feature brief + hard invariants (this session) — authoritative scope/contract.
</content>
</invoke>
