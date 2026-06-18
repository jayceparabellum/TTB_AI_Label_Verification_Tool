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

# --- Persistence (local SQLite) ----------------------------------------------
CHECKPOINT_DB = _path("AGENT_CHECKPOINT_DB", _DATA / "checkpoints.sqlite")
AUDIT_DB = _path("AGENT_AUDIT_DB", _DATA / "audit.sqlite")          # used in U5

# --- RAG (Layer 3, wired in Phase C) -----------------------------------------
CHROMA_DIR = _path("RAG_CHROMA_DIR", _DATA / "chroma")
EMBED_MODEL = os.environ.get("RAG_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "5"))
# Below this fused-retrieval score, regulatory tools REFUSE rather than answer.
RAG_MIN_CONFIDENCE = float(os.environ.get("RAG_MIN_CONFIDENCE", "0.30"))

# --- Dense retrieval (BGE-small, fused with BM25) -----------------------------
# "auto" = use dense when sentence-transformers + the model are importable, else
# fall back to BM25-only; "off" forces BM25-only; "on" requires dense (raises if
# the dependency is missing). Default "auto" keeps the base install fully offline.
RAG_DENSE = os.environ.get("RAG_DENSE", "auto").lower()
# A dense (cosine) hit at or above this similarity can support an answer even when
# lexical term-coverage is thin — lets a genuine semantic match through without
# weakening the refuse gate for unrelated queries.
RAG_DENSE_MIN_SIM = float(os.environ.get("RAG_DENSE_MIN_SIM", "0.55"))

# --- Offline guard ------------------------------------------------------------
# When set, code paths that would reach the public internet must refuse. The
# corpus is fetched at build time and cached; runtime is fully local.
OFFLINE = os.environ.get("OFFLINE", "1") not in {"0", "false", "False"}


def ensure_data_dir() -> Path:
    """Create the local data dir lazily (so importing config has no side effects)."""
    _DATA.mkdir(parents=True, exist_ok=True)
    return _DATA
