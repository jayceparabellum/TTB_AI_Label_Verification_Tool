"""Dense retrieval backend — BGE-small embeddings + an in-memory cosine index,
fused with BM25 in the Retriever via reciprocal-rank fusion (RRF).

Off by default: enabled only when sentence-transformers and the model are
importable (config.RAG_DENSE). The embedder is injectable, so the fusion and
cite-or-refuse contract are tested offline with a deterministic stub — the real
BGE-small run is a one-command host step (pip install sentence-transformers).

Two vector stores, selected by config.RAG_DENSE_STORE:
  - "memory" (default): a plain numpy matrix — exact cosine over a dozen normalized
    chunks, faster and simpler than an ANN index, rebuilt at each startup.
  - "chroma": a persistent Chroma store at config.CHROMA_DIR — the embeddings are
    computed once and reused across restarts, so the model isn't re-run on every boot.
    Opt-in because chromadb is an extra (optional) install.
Both are fully offline at run time once the model is cached locally (chromadb's
anonymized telemetry is disabled).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

from agent import config

from .ingest import Chunk, load_corpus


class Embedder(Protocol):
    """Anything that turns text into vectors. Injected so tests need no model."""

    def encode(self, texts: Sequence[str]) -> np.ndarray:  # -> (n, dim) float array
        ...


class BGEEmbedder:
    """sentence-transformers BGE-small. Lazy-loads the model on first encode so
    importing this module stays cheap and triggers no download."""

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or config.EMBED_MODEL
        self._model = None

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("sentence_transformers") is not None

    def _ensure(self):
        if self._model is None:
            # Honor the offline invariant: at run time load ONLY from the local
            # cache, never letting huggingface_hub phone home to check for updates.
            # The model is provisioned earlier (build step / first run with network);
            # see the Dockerfile.agent note.
            #   - local_files_only is the precise, version-supported control.
            #   - HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE are defense-in-depth: a silent
            #     network call from a locked-down federal host is the failure we will
            #     not risk, so we belt-and-suspenders it.
            from sentence_transformers import SentenceTransformer
            if config.OFFLINE:
                os.environ.setdefault("HF_HUB_OFFLINE", "1")
                os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            try:
                self._model = SentenceTransformer(
                    self.model_name, local_files_only=config.OFFLINE)
            except Exception as exc:
                if config.OFFLINE:
                    raise RuntimeError(
                        f"Dense model {self.model_name!r} is not in the local cache and "
                        f"OFFLINE is set, so it cannot be downloaded at run time. "
                        f"Provision it first (with network): python -c \"from "
                        f"sentence_transformers import SentenceTransformer as S; "
                        f"S('{self.model_name}')\" — or set RAG_DENSE=off to use "
                        f"BM25-only.") from exc
                raise
        return self._model

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        vecs = self._ensure().encode(list(texts), normalize_embeddings=True)
        return np.asarray(vecs, dtype=np.float32)


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


class DenseIndex:
    """In-memory cosine index over the corpus chunks. Duck-types the DenseBackend
    contract used by Retriever: an `available` flag and `search(query, k)`."""

    available = True

    def __init__(self, chunks: list[Chunk], embedder: Embedder):
        self.chunks = chunks
        self.embedder = embedder
        docs = [f"{c.heading}. {c.text}" for c in chunks]
        self._mat = _normalize(embedder.encode(docs))          # (n, dim), normalized

    def search(self, query: str, k: int) -> list[tuple[int, float]]:
        """Return [(chunk_index, cosine_similarity), ...] for the top-k chunks."""
        q = _normalize(self.embedder.encode([query]))[0]        # (dim,)
        sims = self._mat @ q                                    # cosine, (n,)
        order = np.argsort(-sims)[:k]
        return [(int(i), float(sims[i])) for i in order]


_CHROMA_COLLECTION = "ttb_cfr_dense"
_FINGERPRINT_FILE = "dense_fingerprint.json"


def _corpus_fingerprint(chunks: list[Chunk], embedder: Embedder) -> str:
    """Identity of (embedder, corpus). A change here means the persisted vectors are
    stale and must be rebuilt — guards against silently serving embeddings for a
    different model or an edited corpus."""
    h = hashlib.sha256()
    h.update(getattr(embedder, "model_name", embedder.__class__.__name__).encode())
    for c in chunks:
        h.update(b"\x00")
        h.update(f"{c.heading}. {c.text}".encode("utf-8"))
    return h.hexdigest()


class ChromaDenseBackend:
    """Persistent dense index backed by Chroma. Duck-types the DenseBackend contract
    (an `available` flag + `search(query, k)`), like DenseIndex — but the embeddings
    are computed once with the injected embedder and persisted at CHROMA_DIR, so a
    restart reuses them instead of re-running the model. Rebuilds only when the
    corpus + embedder fingerprint changes. Telemetry is disabled (offline invariant)."""

    available = True

    def __init__(self, chunks: list[Chunk], embedder: Embedder,
                 persist_dir: str | None = None):
        import chromadb                                   # optional dep, lazy-imported
        from chromadb.config import Settings

        self.chunks = chunks
        self.embedder = embedder
        self._dir = Path(persist_dir or config.CHROMA_DIR)
        self._dir.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(
            path=str(self._dir), settings=Settings(anonymized_telemetry=False))
        self._col = client.get_or_create_collection(
            _CHROMA_COLLECTION, metadata={"hnsw:space": "cosine"})

        fingerprint = _corpus_fingerprint(chunks, embedder)
        if self._col.count() != len(chunks) or self._stored_fingerprint() != fingerprint:
            self._rebuild(chunks, embedder, fingerprint)

    def _fp_path(self) -> Path:
        return self._dir / _FINGERPRINT_FILE

    def _stored_fingerprint(self) -> str | None:
        try:
            return json.loads(self._fp_path().read_text())["fingerprint"]
        except (OSError, ValueError, KeyError):
            return None

    def _rebuild(self, chunks: list[Chunk], embedder: Embedder, fingerprint: str) -> None:
        stale = self._col.get()["ids"]
        if stale:
            self._col.delete(ids=stale)
        docs = [f"{c.heading}. {c.text}" for c in chunks]
        embs = _normalize(embedder.encode(docs))           # unit vectors, cosine space
        self._col.add(ids=[str(i) for i in range(len(chunks))], embeddings=embs.tolist())
        self._fp_path().write_text(json.dumps({"fingerprint": fingerprint}))

    def search(self, query: str, k: int) -> list[tuple[int, float]]:
        """Return [(chunk_index, cosine_similarity), ...] for the top-k chunks."""
        n = self._col.count()
        if n == 0:
            return []
        q = _normalize(self.embedder.encode([query]))[0]
        res = self._col.query(query_embeddings=[q.tolist()], n_results=min(k, n))
        ids, dists = res["ids"][0], res["distances"][0]
        # cosine space: Chroma returns distance = 1 - cosine_similarity.
        return [(int(i), float(1.0 - d)) for i, d in zip(ids, dists)]


def build_dense_backend(chunks: list[Chunk] | None = None,
                        embedder: Embedder | None = None):
    """Construct the dense backend, honoring config.RAG_DENSE + config.RAG_DENSE_STORE.

    Returns None (BM25-only) when dense is off, or when it's "auto" and
    sentence-transformers isn't installed. Raises only when "on"/`chroma` is requested
    without the dependency, so a misconfigured host fails loudly.
    """
    mode = config.RAG_DENSE
    if mode in {"0", "off", "false", "no"}:
        return None
    if embedder is None:
        if not BGEEmbedder.available():
            if mode in {"1", "on", "true", "yes"}:
                raise RuntimeError(
                    "RAG_DENSE is on but sentence-transformers is not installed; "
                    "`pip install sentence-transformers` or set RAG_DENSE=off.")
            return None                                         # "auto" -> BM25-only
        embedder = BGEEmbedder()
    chunks = chunks if chunks is not None else load_corpus()
    if config.RAG_DENSE_STORE == "chroma":
        if importlib.util.find_spec("chromadb") is None:
            raise RuntimeError(
                "RAG_DENSE_STORE=chroma but chromadb is not installed; "
                "`pip install chromadb` or set RAG_DENSE_STORE=memory.")
        return ChromaDenseBackend(chunks, embedder)
    return DenseIndex(chunks, embedder)
