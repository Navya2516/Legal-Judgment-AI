"""Where each document's search index lives: a FAISS file plus its chunks.

<index_dir>/<doc_id>.faiss   the vectors (IndexFlatIP, exact cosine search)
<index_dir>/<doc_id>.json    the chunk texts, page numbers and build settings

FAISS is read and written through Python file I/O, not FAISS's own path
functions, which can fail on Windows paths containing non-ASCII characters.
"""
import json
import logging
import os
import re
import tempfile
from pathlib import Path

import faiss
import numpy as np
from fastapi import Depends
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.schemas.search import Chunk
from app.utils.errors import StorageError
from app.utils.files import atomic_write_json

logger = logging.getLogger("legal-ai.index")
_DOC_ID = re.compile(r"^[a-f0-9]{32}$")


class IndexMeta(BaseModel):
    embedding_model: str
    embedding_dim: int
    chunk_size: int
    chunk_overlap: int
    cleaning_version: int
    chunk_count: int


class LoadedIndex(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    index: object
    chunks: list[Chunk]
    meta: IndexMeta


class IndexStore:
    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)

    def _paths(self, doc_id: str) -> tuple[Path, Path]:
        if not _DOC_ID.match(doc_id):
            raise ValueError("invalid document id")
        return self._dir / f"{doc_id}.faiss", self._dir / f"{doc_id}.json"

    def exists(self, doc_id: str) -> bool:
        faiss_path, json_path = self._paths(doc_id)
        return faiss_path.exists() and json_path.exists()

    def save(self, doc_id: str, vectors: np.ndarray, chunks: list[Chunk], meta: IndexMeta) -> None:
        faiss_path, json_path = self._paths(doc_id)
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        blob = faiss.serialize_index(index).tobytes()
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(blob)
                os.replace(tmp, faiss_path)
            except OSError:
                Path(tmp).unlink(missing_ok=True)
                raise
            atomic_write_json(
                json_path,
                {"meta": meta.model_dump(), "chunks": [c.model_dump() for c in chunks]},
            )
        except OSError as exc:
            logger.error("Cannot save index for %s: %s", doc_id, exc)
            raise StorageError("The search index could not be saved.") from exc

    def load(self, doc_id: str) -> LoadedIndex:
        faiss_path, json_path = self._paths(doc_id)
        try:
            raw = np.frombuffer(faiss_path.read_bytes(), dtype=np.uint8)
            index = faiss.deserialize_index(raw)
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            chunks = [Chunk.model_validate(c) for c in payload["chunks"]]
            meta = IndexMeta.model_validate(payload["meta"])
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            logger.error("Cannot load index for %s: %s", doc_id, exc)
            raise StorageError("The search index could not be read. Rebuild it.") from exc
        if index.ntotal != len(chunks):
            raise StorageError("The search index is inconsistent. Rebuild it.")
        return LoadedIndex(index=index, chunks=chunks, meta=meta)

    def load_meta(self, doc_id: str) -> IndexMeta | None:
        _, json_path = self._paths(doc_id)
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            return IndexMeta.model_validate(payload["meta"])
        except (OSError, ValueError, KeyError):
            return None

    def delete(self, doc_id: str) -> None:
        for path in self._paths(doc_id):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.error("Cannot delete %s: %s", path.name, exc)
                raise StorageError("The search index could not be deleted.") from exc


def get_index_store(settings: Settings = Depends(get_settings)) -> IndexStore:
    return IndexStore(settings.index_path)
