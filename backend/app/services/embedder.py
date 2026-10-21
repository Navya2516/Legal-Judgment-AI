"""Text embeddings. The real model is loaded lazily, on first use.

An `Embedder` turns texts into L2-normalised float32 vectors, so the inner
product of two vectors equals their cosine similarity.
"""
import logging
import threading
from typing import Callable, Protocol

import numpy as np

from app.config import get_settings

logger = logging.getLogger("legal-ai.embedder")


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, batch_size: int = 32) -> None:
        self.name = model_name
        self._batch_size = batch_size
        self._model = None
        self._lock = threading.Lock()
        self.dim = 0

    def _load(self):
        with self._lock:
            if self._model is None:
                logger.info("Loading embedding model %s (first use may download it)", self.name)
                from sentence_transformers import SentenceTransformer  # heavy import

                self._model = SentenceTransformer(self.name)
                # Newer sentence-transformers renamed this method; support both.
                get_dim = getattr(self._model, "get_embedding_dimension", None) or getattr(
                    self._model, "get_sentence_embedding_dimension"
                )
                self.dim = int(get_dim())
        return self._model

    def warm_up(self) -> None:
        """Load the model now (used by the optional startup preload)."""
        self._load()

    def embed(self, texts: list[str]) -> np.ndarray:
        model = self._load()
        vectors = model.encode(
            texts,
            batch_size=self._batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.ascontiguousarray(vectors, dtype=np.float32)


_embedder: Embedder | None = None
_embedder_lock = threading.Lock()


def get_embedder() -> Embedder:
    """One shared embedder per process, so the model is loaded only once."""
    global _embedder
    with _embedder_lock:
        if _embedder is None or _embedder.name != get_settings().embedding_model:
            _embedder = SentenceTransformerEmbedder(get_settings().embedding_model)
        return _embedder


def get_embedder_factory() -> Callable[[], Embedder]:
    """A dependency, so tests can swap in a fast fake embedder."""
    return get_embedder
