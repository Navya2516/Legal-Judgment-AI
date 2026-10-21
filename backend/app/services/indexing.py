"""Build and query a document's search index."""
import logging
from typing import Callable, Optional

import numpy as np

from app.config import Settings
from app.schemas.search import IndexInfo, IndexStatus, SearchHit
from app.services.chunker import CLEANING_VERSION, chunk_pages
from app.services.document_store import DocumentStore
from app.services.embedder import Embedder
from app.services.index_store import IndexMeta, IndexStore, LoadedIndex
from app.services.page_store import PageStore
from app.utils.errors import ConflictError

logger = logging.getLogger("legal-ai.indexing")


def build_document_index(
    doc_id: str,
    *,
    store: DocumentStore,
    page_store: PageStore,
    index_store: IndexStore,
    settings: Settings,
    get_embedder: Callable[[], Embedder],
) -> None:
    """Chunk the extracted text, embed it and save the FAISS index.

    Runs in the background. Never raises: failure is recorded on the document
    as index_status "failed" with a plain reason.
    """
    if store.get(doc_id) is None:
        return
    store.update(doc_id, index_status="indexing", index_error=None, chunk_count=0)
    try:
        pages = page_store.load(doc_id)
        chunks = chunk_pages(pages, settings.chunk_size, settings.chunk_overlap)
        if not chunks:
            raise ValueError("no chunks")
        embedder = get_embedder()
        vectors = embedder.embed([c.text for c in chunks])
        if vectors.shape[0] != len(chunks):
            raise RuntimeError("embedder returned the wrong number of vectors")
        meta = IndexMeta(
            embedding_model=embedder.name,
            embedding_dim=int(vectors.shape[1]),
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            cleaning_version=CLEANING_VERSION,
            chunk_count=len(chunks),
        )
        index_store.save(doc_id, vectors, chunks, meta)
        if store.update(doc_id, index_status="ready", chunk_count=len(chunks)) is None:
            index_store.delete(doc_id)  # deleted while indexing
        logger.info("Indexed %s: %d chunks", doc_id, len(chunks))
    except Exception as exc:
        logger.exception("Indexing failed for %s", doc_id)
        if isinstance(exc, ImportError):
            reason = "The embedding library is not installed. Run: pip install sentence-transformers"
        elif isinstance(exc, ValueError) and str(exc) == "no chunks":
            reason = "The document has no text that can be searched."
        else:
            reason = (
                "The search index could not be built. If this is the first run, the "
                "embedding model may still need to download; check your internet and retry."
            )
        try:
            store.update(doc_id, index_status="failed", index_error=reason)
        except Exception:
            logger.exception("Could not record the indexing failure for %s", doc_id)


def is_stale(meta: IndexMeta, settings: Settings) -> bool:
    return (
        meta.embedding_model != settings.embedding_model
        or meta.chunk_size != settings.chunk_size
        or meta.chunk_overlap != settings.chunk_overlap
        or meta.cleaning_version != CLEANING_VERSION
    )


def index_info(doc_id: str, store: DocumentStore, index_store: IndexStore, settings: Settings) -> IndexInfo:
    record = store.get(doc_id)
    status = IndexStatus(record.index_status) if record else IndexStatus.none
    meta: Optional[IndexMeta] = index_store.load_meta(doc_id) if index_store.exists(doc_id) else None
    return IndexInfo(
        document_id=doc_id,
        index_status=status,
        chunk_count=meta.chunk_count if meta else 0,
        embedding_model=meta.embedding_model if meta else None,
        embedding_dim=meta.embedding_dim if meta else None,
        chunk_size=meta.chunk_size if meta else None,
        chunk_overlap=meta.chunk_overlap if meta else None,
        stale=bool(meta and is_stale(meta, settings)),
        error=record.index_error if record else None,
    )


def search_index(
    loaded: LoadedIndex, embedder: Embedder, query: str, top_k: int
) -> list[SearchHit]:
    if loaded.meta.embedding_model != embedder.name:
        raise ConflictError(
            "This index was built with a different embedding model. Rebuild it.",
            code="index_stale",
        )
    vector = embedder.embed([query])
    k = min(top_k, loaded.index.ntotal)
    scores, ids = loaded.index.search(np.ascontiguousarray(vector, dtype=np.float32), k)
    hits: list[SearchHit] = []
    for score, idx in zip(scores[0], ids[0]):
        if idx < 0:
            continue
        hits.append(
            SearchHit(rank=len(hits) + 1, score=round(float(score), 4), chunk=loaded.chunks[int(idx)])
        )
    return hits
