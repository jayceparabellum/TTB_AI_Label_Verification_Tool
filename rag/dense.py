"""Dense retrieval backend — BGE-small embeddings + an in-memory cosine index,
fused with BM25 in the Retriever via reciprocal-rank fusion (RRF).

Off by default: enabled only when sentence-transformers and the model are
importable (config.RAG_DENSE). The embedder is injectable, so the fusion and
cite-or-refuse contract are tested offline with a deterministic stub — the real
BGE-small run is a one-command host step (pip install sentence-transformers).

The vector store is plain numpy: the corpus is tiny (a dozen chunks), so an exact
cosine over a normalized matrix is faster and simpler than an ANN index. Chroma
persistence (config.CHROMA_DIR) is a deferred optimization for a much larger
corpus, not needed at this scale. Fully offline at run time once the model is
cached locally.
"""

from __future__ import annotations

import importlib.util
import os
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


def build_dense_backend(chunks: list[Chunk] | None = None,
                        embedder: Embedder | None = None) -> DenseIndex | None:
    """Construct the dense backend, honoring config.RAG_DENSE.

    Returns None (BM25-only) when dense is off, or when it's "auto" and
    sentence-transformers isn't installed. Raises only when "on" is requested
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
    return DenseIndex(chunks if chunks is not None else load_corpus(), embedder)
