"""Analysis routes: summary, provisions and provision explanations."""
import logging
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Query

from app.config import Settings, get_settings
from app.routes.documents import ERRORS_READY, DocId, _get_ready_record
from app.schemas.analysis import (
    ProvisionExplainRequest,
    ProvisionExplanations,
    ProvisionList,
    SummaryResult,
)
from app.schemas.common import ErrorResponse
from app.services.analysis import explain_provisions, generate_summary, list_provisions
from app.services.document_store import DocumentStore, get_document_store
from app.services.embedder import Embedder, get_embedder_factory
from app.services.index_store import IndexStore, get_index_store
from app.services.llm import LlmClient, LlmError, get_llm_factory
from app.services.page_store import PageStore, get_page_store
from app.services.results_store import ResultStore, get_result_store
from app.utils.errors import NotFoundError

logger = logging.getLogger("legal-ai.analysis")

router = APIRouter(prefix="/api/v1/documents", tags=["analysis"])

ERRORS_LLM = {
    **ERRORS_READY,
    429: {"model": ErrorResponse},
    502: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


def _llm(factory: Callable[[], LlmClient]) -> LlmClient:
    try:
        return factory()
    except LlmError as exc:
        raise exc.to_app_error() from exc


@router.post("/{doc_id}/summary", response_model=SummaryResult, responses=ERRORS_LLM)
def create_summary(
    doc_id: DocId,
    settings: Settings = Depends(get_settings),
    store: DocumentStore = Depends(get_document_store),
    page_store: PageStore = Depends(get_page_store),
    index_store: IndexStore = Depends(get_index_store),
    results: ResultStore = Depends(get_result_store),
    llm_factory: Callable[[], LlmClient] = Depends(get_llm_factory),
    embedder_factory: Callable[[], Embedder] = Depends(get_embedder_factory),
) -> SummaryResult:
    """Generate (and save) a plain-language summary with page citations.

    Takes up to a minute because it calls the language model. Every point is
    checked against the judgment's own text; points that cannot be traced to a
    page are removed, and `grounding` reports how many.
    """
    _get_ready_record(doc_id, store)
    llm = _llm(llm_factory)
    try:
        result = generate_summary(
            doc_id,
            pages=page_store.load(doc_id),
            settings=settings,
            index_store=index_store,
            get_embedder=embedder_factory,
            llm=llm,
        )
    except LlmError as exc:
        raise exc.to_app_error() from exc
    results.save(doc_id, "summary", result.model_dump(mode="json"))
    return result


@router.get("/{doc_id}/summary", response_model=SummaryResult, responses=ERRORS_READY)
def get_summary(
    doc_id: DocId,
    store: DocumentStore = Depends(get_document_store),
    results: ResultStore = Depends(get_result_store),
) -> SummaryResult:
    """The last saved summary (no model call)."""
    _get_ready_record(doc_id, store)
    saved = results.load(doc_id, "summary")
    if saved is None:
        raise NotFoundError("No summary has been generated yet. Use POST /summary.", code="not_generated")
    return SummaryResult.model_validate(saved)


@router.get("/{doc_id}/provisions", response_model=ProvisionList, responses=ERRORS_READY)
def get_provisions(
    doc_id: DocId,
    min_mentions: Annotated[int, Query(ge=1, le=1000)] = 1,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    store: DocumentStore = Depends(get_document_store),
    page_store: PageStore = Depends(get_page_store),
) -> ProvisionList:
    """Articles, Sections and Rules mentioned in the judgment, most-mentioned first.

    Found by pattern search over every page; no language model is used.
    """
    _get_ready_record(doc_id, store)
    return list_provisions(doc_id, page_store.load(doc_id), min_mentions=min_mentions, limit=limit)


@router.post("/{doc_id}/provisions/explain", response_model=ProvisionExplanations, responses=ERRORS_LLM)
def create_provision_explanations(
    doc_id: DocId,
    body: ProvisionExplainRequest = ProvisionExplainRequest(),
    settings: Settings = Depends(get_settings),
    store: DocumentStore = Depends(get_document_store),
    page_store: PageStore = Depends(get_page_store),
    results: ResultStore = Depends(get_result_store),
    llm_factory: Callable[[], LlmClient] = Depends(get_llm_factory),
) -> ProvisionExplanations:
    """Explain the role of the most-mentioned provisions in this judgment (saved)."""
    _get_ready_record(doc_id, store)
    llm = _llm(llm_factory)
    try:
        result = explain_provisions(doc_id, page_store.load(doc_id), top_n=body.top_n, llm=llm, strict=settings.llm_drop_unverified)
    except LlmError as exc:
        raise exc.to_app_error() from exc
    results.save(doc_id, "provisions", result.model_dump(mode="json"))
    return result


@router.get("/{doc_id}/provisions/explain", response_model=ProvisionExplanations, responses=ERRORS_READY)
def get_provision_explanations(
    doc_id: DocId,
    store: DocumentStore = Depends(get_document_store),
    results: ResultStore = Depends(get_result_store),
) -> ProvisionExplanations:
    """The last saved provision explanations (no model call)."""
    _get_ready_record(doc_id, store)
    saved = results.load(doc_id, "provisions")
    if saved is None:
        raise NotFoundError("No explanations have been generated yet.", code="not_generated")
    return ProvisionExplanations.model_validate(saved)
