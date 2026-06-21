# Runbook: Verify durable Postgres audit storage (PRD 0003)

- **Status:** Ready to execute
- **Owner:** whoever runs the verification (needs repo + Render access)
- **Closes:** the [PRD 0003 post-merge verification checklist](../prds/0003-durable-audit-storage.md#post-merge-verification)

## Why this exists

PRD 0003 made the audit log + chat checkpoints durable on Postgres, but the live
path was **config-tested only** — no Postgres was available when it was built. This
runbook proves the real thing end to end before anyone relies on durability in
production. Two paths:

- **Part A (local, ~10 min):** a throwaway Postgres proves persistence, concurrency,
  chain integrity, and the checkpointer — fast, no Render needed.
- **Part B (Render, ~20 min):** the production-realistic proof — a recorded approval
  survives an actual redeploy.

Run **Part A first** (cheap, catches most issues), then **Part B** to close the
redeploy-survival box.

## Prerequisites

- Repo cloned, `.venv` set up (`pip install -r requirements.txt`), tests green locally.
- For Part A: Docker, **or** any reachable Postgres DSN.
- For Part B: a Render account with access to the `ttb-label-verification` blueprint.
- A psql client is handy but optional (`psql` ships on most systems).

> **DSN note:** Render hands out `postgres://…` DSNs. The app normalizes these to
> `postgresql+psycopg://…` for SQLAlchemy automatically (`config.audit_db_url`), and
> psycopg accepts the raw form for the checkpointer — so paste the DSN **verbatim**
> wherever this runbook uses `DATABASE_URL` / `TEST_DATABASE_URL`.

---

## Part A — Local verification against a throwaway Postgres

### A1. Start a Postgres and export its DSN

```bash
# Option 1 — Docker (throwaway; data lives only for this container)
docker run -d --name ttb-pg -e POSTGRES_PASSWORD=pw -p 5432:5432 postgres:16
export TEST_DATABASE_URL="postgres://postgres:pw@127.0.0.1:5432/postgres"

# Option 2 — any existing/managed Postgres: just export its DSN
# export TEST_DATABASE_URL="postgres://user:pass@host:5432/dbname"
```

### A2. Run the gated round-trip test (the canonical check)

```bash
TEST_DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/python -m pytest \
  tests/test_durable_audit.py::test_postgres_round_trip -q
```

✅ **Expect:** `1 passed`. This records an audit row through the real SQLAlchemy +
psycopg path on Postgres and reads it back.

### A3. Prove persistence across a process restart

Write rows in one process, then read them back in a **fresh** process (no shared
in-memory state) — this is what a redeploy does:

```bash
# process 1: write + verify the chain
DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/python -c "
from agent import audit
audit.record('agent-user','override','runbook-A','FLAG','PASS','runbook persistence check')
print('chain:', audit.verify())
print('rows:', [r['target_result_id'] for r in audit.all_rows()])
"

# process 2: a brand-new interpreter — the row must still be there
DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/python -c "
from agent import audit
rows = audit.all_rows()
assert any(r['target_result_id']=='runbook-A' for r in rows), 'ROW DID NOT PERSIST'
print('PERSISTED:', len(rows), 'row(s);', audit.verify().message)
"
```

✅ **Expect:** process 2 prints `PERSISTED: …` and `chain intact (…)`. If it raised
`ROW DID NOT PERSIST`, the data isn't durable — stop and investigate.

### A4. Concurrency + tamper-evidence on Postgres (optional but recommended)

```bash
# Concurrency: the durable-audit suite's concurrency test, pointed at Postgres.
DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/python -c "
from agent import audit
import concurrent.futures as cf
with cf.ThreadPoolExecutor(max_workers=8) as ex:
    list(ex.map(lambda i: audit.record('u','override',f'c{i}',None,'PASS',f'r{i}'), range(40)))
v = audit.verify()
print('after 40 concurrent writes:', v.ok, '|', v.message)
assert v.ok, v
"
```

✅ **Expect:** `True | chain intact (…)` — no forked chain under concurrent writers
(the `FOR UPDATE` tail lock holds on Postgres).

### A5. Checkpointer (PostgresSaver) connects + sets up

```bash
DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/python -c "
import app.agent_chat as ac
print('checkpointer:', type(ac._SAVER).__name__)
"
```

✅ **Expect:** `checkpointer: PostgresSaver` (it lazily imported the Postgres saver,
opened the connection, and ran `setup()` to create the checkpoint tables without
error). Anything else (e.g. `SqliteSaver`) means `DATABASE_URL` wasn't picked up.

### A6. (Optional) eyeball the rows

```bash
psql "$TEST_DATABASE_URL" -c \
  "select id, actor, action, new_verdict, reason, substr(row_hash,1,12) as row_hash from audit order by id;"
```

### A7. Tear down

```bash
docker rm -f ttb-pg          # if you used the Docker option
```

---

## Part B — Render verification (redeploy survival)

This closes the **"an approval survives a real redeploy"** box — the one thing Part A
can't prove.

### B1. Deploy via the Blueprint (provisions Postgres + wires DATABASE_URL)

The managed Postgres and `DATABASE_URL` come from `render.yaml`, so deploy with a
**Blueprint**, not the bare `scripts/deploy_render.sh` (that creates only the web
service, no database):

1. Render dashboard → **New + → Blueprint** → connect this repo → it reads
   `render.yaml` and creates the `ttb-label-verification` web service **and** the
   `ttb-audit-db` Postgres, wiring `DATABASE_URL` into the service.
2. Wait for the first deploy to go live; confirm `GET /health` returns OK.

> Free Postgres expires after 90 days — fine for verification, upgrade for anything
> lasting.

### B2. Confirm the app is actually on Postgres

In the Render **Shell** for the web service:

```bash
python -c "import app.agent_chat as ac, agent.config as c; \
print('store:', type(ac._SAVER).__name__, '| url:', c.audit_db_url()[:18])"
```

✅ **Expect:** `store: PostgresSaver | url: postgresql+psyco…`. If it says
`SqliteSaver` / `sqlite:///`, the env var isn't wired — fix before continuing.

### B3. Record an approval through the confirm gate

On the live site's **/chat**:

1. Verify (or upload) a label so there's a result to act on.
2. Ask the assistant to override it, e.g. *"Override the last result to PASS — manual
   review confirms the warning is compliant."*
3. The **confirm gate** pauses; click **Approve**. This writes an append-only audit
   row (`action=override`) — the durable record under test.
4. Note the recorded id from the assistant's reply.

### B4. Read it back (before redeploy)

Ask the assistant: *"Export the audit log."* → it returns a CSV/XLSX via
`export_audit_log`. Confirm your override row is present (filename, actor
`agent-user`, your reason). Or, from the Render Shell:

```bash
psql "$DATABASE_URL" -c "select id, action, new_verdict, reason from audit order by id desc limit 5;"
```

### B5. Trigger a real redeploy

Render dashboard → the web service → **Manual Deploy → Deploy latest commit**
(or `git commit --allow-empty -m "redeploy: durability check" && git push`, since
`autoDeploy` is on). Wait for it to go live again.

### B6. Confirm survival

After the redeploy completes, **without re-recording anything**:

- Ask the assistant again: *"Export the audit log"* → your override row from B3 is
  **still there**. ✅
- Chain still intact, from the Render Shell:
  ```bash
  python -c "from agent import audit; print(audit.verify())"
  ```
  ✅ **Expect:** `VerifyResult(ok=True, …, 'chain intact (N rows)')`.
- **Checkpoint survival (optional):** before B5, leave a chat thread mid-conversation;
  after the redeploy, continue it and confirm the assistant still has the thread's
  context (the `PostgresSaver` checkpoint persisted).

If the row is **gone** after redeploy, durability is not working — capture the logs
and reopen PRD 0003.

---

## Part C — PII / checkpoint scoping review (PRD 0003 open question)

Durable checkpoints persist conversation state, which can include label text. With a
real Postgres now holding it, decide and record:

- Is persisting chat/label text in the durable checkpoint acceptable under the
  "no PII at rest" invariant, or should checkpoints stay ephemeral (SQLite) while only
  the **audit log** goes to Postgres?
- If checkpoints must not persist sensitive text, the follow-up is to split the two
  stores (audit → Postgres, checkpoints → ephemeral) — file it as a new issue/PRD.

Write the decision into PRD 0003 (or a short ADR) so it isn't relitigated.

---

## Sign-off

Check these back on the [PRD 0003 checklist](../prds/0003-durable-audit-storage.md#post-merge-verification):

- [ ] **Live Postgres round-trip** — Part A2 (`test_postgres_round_trip` passed) +/or A3.
- [ ] **Approval survives a real redeploy** — Part B6 (override row present post-redeploy).
- [ ] **PostgresSaver checkpointer verified** — Part A5 / B2 (+ B6 checkpoint survival).
- [ ] **PII / checkpoint scoping revisited** — Part C decision recorded.

## Rollback / cleanup

- **Local:** `docker rm -f ttb-pg`; the gated test and one-liners write only throwaway
  rows.
- **Render:** to revert to SQLite, remove the `DATABASE_URL` env var (and optionally the
  `ttb-audit-db` database) — the app falls back to ephemeral local SQLite, no code change.
- The verification override rows (`runbook-*`) are harmless test entries; the log is
  append-only by design, so leave them or start a fresh database.
