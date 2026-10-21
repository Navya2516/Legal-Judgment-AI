"""Retrieval routes: index status/rebuild, browse chunks, semantic search."""
import logging
from typing import Annotated, Callable

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.routes.documents import ERRORS_READ, ERRORS_READY, DocId, _get_ready_record, _get_record
from app.schemas.common import ErrorResponse
from app.schemas.search import (
    ChunkList,
    IndexInfo,
    IndexStatus,
    SearchRequest,
    SearchResponse,
)
from app.services.document_store import DocumentStore, get_document_store
from app.services.embedder import Embedder, get_embedder_factory
from app.services.index_store import IndexStore, get_index_store
from app.services.indexing import build_document_index, index_info, is_stale, search_index
from app.services.page_store import PageStore, get_page_store
from app.utils.errors import ConflictError

logger = logging.getLogger("legal-ai.retrieval")

router = APIRouter(prefix="/api/v1/documents", tags=["retrieval"])


def _require_index(doc_id: str, store: DocumentStore, index_store: IndexStore, settings: Settings):
    record = _get_ready_record(doc_id, store)
    status = record.index_status
    if status == "indexing":
        raise ConflictError("The search index is still being built. Try again shortly.", code="index_not_ready")
    if status == "failed":
        raise ConflictError(
            record.index_error or "The search index failed to build. Rebuild it.",
            code="index_failed",
        )
    if status != "ready" or not index_store.exists(doc_id):
        raise ConflictError(
            "This document has no search index yet. Build it with POST /index.",
            code="index_not_ready",
        )
    loaded = index_store.load(doc_id)
    if is_stale(loaded.meta, settings):
        raise ConflictError(
            "The index was built with different settings. Rebuild it with POST /index.",
            code="index_stale",
        )
    return loaded


@router.get("/{doc_id}/index", response_model=IndexInfo, responses=ERRORS_READ)
def get_index_info(
    doc_id: DocId,
    settings: Settings = Depends(get_settings),
    store: DocumentStore = Depends(get_document_store),
    index_store: IndexStore = Depends(get_index_store),
) -> IndexInfo:
    """Index status, chunk count and the settings it was built with."""
    _get_record(doc_id, store)
    return index_info(doc_id, store, index_store, settings)


@router.post("/{doc_id}/index", response_model=IndexInfo, status_code=202, responses=ERRORS_READY)
def rebuild_index(
    doc_id: DocId,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
    store: DocumentStore = Depends(get_document_store),
    page_store: PageStore = Depends(get_page_store),
    index_store: IndexStore = Depends(get_index_store),
    embedder_factory: Callable[[], Embedder] = Depends(get_embedder_factory),
) -> IndexInfo:
    """(Re)build the search index, e.g. after changing chunk or model settings."""
    record = _get_ready_record(doc_id, store)
    if record.index_status == "indexing":
        raise ConflictError("The index is already being built.", code="index_busy")
    store.update(doc_id, index_status="indexing", index_error=None)
    background_tasks.add_task(
        build_document_index,
        doc_id,
        store=store,
        page_store=page_store,
        index_store=index_store,
        settings=settings,
        get_embedder=embedder_factory,
    )
    info = index_info(doc_id, store, index_store, settings)
    info.index_status = IndexStatus.indexing
    return info


@router.get("/{doc_id}/chunks", response_model=ChunkList, responses=ERRORS_READY)
def list_chunks(
    doc_id: DocId,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    settings: Settings = Depends(get_settings),
    store: DocumentStore = Depends(get_document_store),
    index_store: IndexStore = Depends(get_index_store),
) -> ChunkList:
    """Browse the chunks the index was built from (to inspect what is searchable)."""
    loaded = _require_index(doc_id, store, index_store, settings)
    page = loaded.chunks[offset : offset + limit]
    return ChunkList(
        document_id=doc_id, chunks=page, total=len(loaded.chunks), offset=offset, limit=limit
    )


@router.post("/{doc_id}/search", response_model=SearchResponse, responses=ERRORS_READY)
async def search_document(
    doc_id: DocId,
    body: SearchRequest,
    settings: Settings = Depends(get_settings),
    store: DocumentStore = Depends(get_document_store),
    index_store: IndexStore = Depends(get_index_store),
    embedder_factory: Callable[[], Embedder] = Depends(get_embedder_factory),
) -> SearchResponse:
    """Find the passages of this judgment closest in meaning to the query.

    Results carry page numbers (physical PDF pages). Nothing is generated here:
    these are the raw passages that later phases will use as evidence.
    """
    loaded = await run_in_threadpool(_require_index, doc_id, store, index_store, settings)
    top_k = body.top_k or settings.top_k
    hits = await run_in_threadpool(search_index, loaded, embedder_factory(), body.query, top_k)
    return SearchResponse(
        document_id=doc_id,
        query=body.query,
        top_k=top_k,
        embedding_model=loaded.meta.embedding_model,
        hits=hits,
    )
