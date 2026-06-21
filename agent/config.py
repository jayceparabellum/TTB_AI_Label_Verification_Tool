"""Single config surface for the agent (Layer 2) and RAG (Layer 3).

All values are local/offline by construction. The exact model is an
implementation-time unknown pending a host spike (see the plan); override via
env without code changes.
"""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / ".agent_data"        # local, gitignored; created on first use


def _path(env: str, default: Path) -> Path:
    return Path(os.environ.get(env, str(default)))


# --- LLM backend --------------------------------------------------------------
# Which chat model the agent uses. Default "ollama" = a LOCAL model, fully offline
# (the original invariant). Set LLM_BACKEND=anthropic on a deployed host that has
# no local model (e.g. Render) to use Claude via the cloud API — this is an
# explicit, opt-in relaxation of "fully offline" for that deploy only; local and
# air-gapped runs leave it unset and stay offline.
LLM_BACKEND = os.environ.get("LLM_BACKEND", "ollama").lower()
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE",
                                       os.environ.get("OLLAMA_TEMPERATURE", "0.0")))

# --- Local model (Ollama) -----------------------------------------------------
# Small 3B model by default (locked decision Q1); swap via OLLAMA_MODEL after the
# host spike picks the winner between llama3.2:3b and qwen2.5:3b-instruct.
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_TEMPERATURE = LLM_TEMPERATURE

# --- Cloud model (Anthropic Claude) -------------------------------------------
# Used only when LLM_BACKEND=anthropic. The key is read from ANTHROPIC_API_KEY by
# the client (set it as a host secret; never commit it). A fast tool-calling model
# by default; override with ANTHROPIC_MODEL.
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# --- Persistence -------------------------------------------------------------
# Default is local SQLite, fully offline (the original invariant). On a durable
# host, set DATABASE_URL to a Postgres DSN and BOTH the append-only audit log and
# the agent's conversation checkpoints persist there instead — surviving the
# redeploys that wipe Render's ephemeral disk. Unset (the default) keeps SQLite,
# so local and air-gapped runs stay offline with no Postgres dependency.
CHECKPOINT_DB = _path("AGENT_CHECKPOINT_DB", _DATA / "checkpoints.sqlite")
AUDIT_DB = _path("AGENT_AUDIT_DB", _DATA / "audit.sqlite")          # used in U5
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


def is_postgres_url(url: str) -> bool:
    """True for a Postgres DSN (the durable backend); False for SQLite/empty."""
    return url.startswith(("postgres://", "postgresql://", "postgresql+"))


def audit_db_url() -> str:
    """SQLAlchemy URL for the audit log, resolved at call time.

    DATABASE_URL when set (durable Postgres); otherwise a SQLite file at AUDIT_DB.
    Read live (not cached) so tests can repoint AUDIT_DB. Render hands out
    `postgres://` DSNs, which SQLAlchemy 2.x rejects — normalize to the psycopg
    driver form so the same DSN works unchanged.
    """
    if DATABASE_URL:
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url
    ensure_data_dir()
    return f"sqlite:///{AUDIT_DB}"

# --- RAG (Layer 3, wired in Phase C) -----------------------------------------
CHROMA_DIR = _path("RAG_CHROMA_DIR", _DATA / "chroma")
EMBED_MODEL = os.environ.get("RAG_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "5"))
# Below this term-coverage score, regulatory tools REFUSE rather than answer.
# Calibrated against eval/rag_golden.json (2026-06-19): in-corpus questions score
# coverage >= 0.667 (BM25-only and dense regimes alike), so 0.50 keeps every golden
# answer while refusing thin-overlap off-corpus queries (e.g. "QR code requirements",
# coverage 0.33) that the old 0.30 floor wrongly answered. NOTE: this does NOT catch
# high-vocab-overlap off-corpus queries ("Serving Facts panels" ~0.57 BM25-only,
# "pictorial health warnings" ~0.83) — those share too much corpus vocabulary to
# separate by coverage without risking real-query recall; a distinguishing-term /
# answer-faithfulness check is the proper fix (follow-up, not a threshold).
RAG_MIN_CONFIDENCE = float(os.environ.get("RAG_MIN_CONFIDENCE", "0.50"))

# --- Dense retrieval (BGE-small, fused with BM25) -----------------------------
# "auto" = use dense when sentence-transformers + the model are importable, else
# fall back to BM25-only; "off" forces BM25-only; "on" requires dense (raises if
# the dependency is missing). Default "auto" keeps the base install fully offline.
RAG_DENSE = os.environ.get("RAG_DENSE", "auto").lower()
# A dense (cosine) hit at or above this similarity can support an answer when lexical
# term-coverage is thin. Set high (just above the ~0.79 dense_sim of off-corpus
# topically-adjacent queries) so the dense rescue can't re-admit what the coverage
# gate just refused — dense_sim alone does NOT separate in- from off-corpus here
# (in-corpus ranges 0.735-0.917, overlapping off-corpus 0.74-0.79), so coverage is the
# primary gate and dense is only a high-confidence assist.
RAG_DENSE_MIN_SIM = float(os.environ.get("RAG_DENSE_MIN_SIM", "0.80"))

# --- Offline guard ------------------------------------------------------------
# When set, code paths that would reach the public internet must refuse. The
# corpus is fetched at build time and cached; runtime is fully local.
OFFLINE = os.environ.get("OFFLINE", "1") not in {"0", "false", "False"}


def ensure_data_dir() -> Path:
    """Create the local data dir lazily (so importing config has no side effects)."""
    _DATA.mkdir(parents=True, exist_ok=True)
    return _DATA
