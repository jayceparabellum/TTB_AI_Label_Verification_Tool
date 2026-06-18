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


# --- Local model (Ollama) -----------------------------------------------------
# Small 3B model by default (locked decision Q1); swap via OLLAMA_MODEL after the
# host spike picks the winner between llama3.2:3b and qwen2.5:3b-instruct.
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
# Keep token generation snappy for a chat panel; verification never waits on this.
OLLAMA_TEMPERATURE = float(os.environ.get("OLLAMA_TEMPERATURE", "0.0"))

# --- Persistence (local SQLite) ----------------------------------------------
CHECKPOINT_DB = _path("AGENT_CHECKPOINT_DB", _DATA / "checkpoints.sqlite")
AUDIT_DB = _path("AGENT_AUDIT_DB", _DATA / "audit.sqlite")          # used in U5

# --- RAG (Layer 3, wired in Phase C) -----------------------------------------
CHROMA_DIR = _path("RAG_CHROMA_DIR", _DATA / "chroma")
EMBED_MODEL = os.environ.get("RAG_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "5"))
# Below this fused-retrieval score, regulatory tools REFUSE rather than answer.
RAG_MIN_CONFIDENCE = float(os.environ.get("RAG_MIN_CONFIDENCE", "0.30"))

# --- Offline guard ------------------------------------------------------------
# When set, code paths that would reach the public internet must refuse. The
# corpus is fetched at build time and cached; runtime is fully local.
OFFLINE = os.environ.get("OFFLINE", "1") not in {"0", "false", "False"}


def ensure_data_dir() -> Path:
    """Create the local data dir lazily (so importing config has no side effects)."""
    _DATA.mkdir(parents=True, exist_ok=True)
    return _DATA
