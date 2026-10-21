"""Continuation routes: what the judgment says happens next, plus general information."""
import logging
from typing import Annotated, Callable, Optional

from fastapi import APIRouter, Depends, Query

from app.config import Settings, get_settings
from app.routes.analysis import ERRORS_LLM, _llm
from app.routes.documents import ERRORS_READY, DocId, _get_ready_record
from app.routes.translation import LangCode, _language
from app.schemas.continuation import ContinuationResult, CourtLevel, TranslatedContinuation
from app.services.continuation import generate_continuation
from app.services.document_store import DocumentStore, get_document_store
from app.services.embedder import Embedder, get_embedder_factory
from app.services.index_store import IndexStore, get_index_store
from app.services.llm import LlmClient, LlmError, get_llm_factory
from app.services.page_store import PageStore, get_page_store
from app.services.results_store import ResultStore, get_result_store
from app.services.translation import english_continuation, translate_continuation
from app.utils.errors import NotFoundError

logger = logging.getLogger("legal-ai.continuation")

router = APIRouter(prefix="/api/v1/documents", tags=["continuation"])


def _source(doc_id: str, results: ResultStore) -> ContinuationResult:
    saved = results.load(doc_id, "continuation")
    if saved is None:
        raise NotFoundError(
            "No continuation insights have been generated yet. Use POST /continuation first.",
            code="not_generated",
        )
    return ContinuationResult.model_validate(saved)


@router.post("/{doc_id}/continuation", response_model=ContinuationResult, responses=ERRORS_LLM)
def create_continuation(
    doc_id: DocId,
    court_level: Annotated[
        Optional[CourtLevel],
        Query(description="Set this only if the court level was detected wrongly."),
    ] = None,
    settings: Settings = Depends(get_settings),
    store: DocumentStore = Depends(get_document_store),
    page_store: PageStore = Depends(get_page_store),
    index_store: IndexStore = Depends(get_index_store),
    results: ResultStore = Depends(get_result_store),
    llm_factory: Callable[[], LlmClient] = Depends(get_llm_factory),
    embedder_factory: Callable[[], Embedder] = Depends(get_embedder_factory),
) -> ContinuationResult:
    """What the judgment says about how the case ended and what happens next (saved).

    Two separate parts. The points about the disposition, directions, deadlines
    and further proceedings come from the judgment and are checked against its
    text. The `avenues` are fixed general information chosen by the court level:
    they do not come from the judgment and they are not advice.
    """
    _get_ready_record(doc_id, store)
    llm = _llm(llm_factory)
    try:
        result = generate_continuation(
            doc_id,
            pages=page_store.load(doc_id),
            settings=settings,
            index_store=index_store,
            get_embedder=embedder_factory,
            llm=llm,
            court_level=court_level,
        )
    except LlmError as exc:
        raise exc.to_app_error() from exc
    results.save(doc_id, "continuation", result.model_dump(mode="json"))
    return result


@router.get("/{doc_id}/continuation", response_model=ContinuationResult, responses=ERRORS_READY)
def get_continuation(
    doc_id: DocId,
    store: DocumentStore = Depends(get_document_store),
    results: ResultStore = Depends(get_result_store),
) -> ContinuationResult:
    """The last saved continuation insights (no model call)."""
    _get_ready_record(doc_id, store)
    return _source(doc_id, results)


@router.post(
    "/{doc_id}/continuation/{lang}", response_model=TranslatedContinuation, responses=ERRORS_LLM
)
def create_continuation_translation(
    doc_id: DocId,
    lang: LangCode,
    settings: Settings = Depends(get_settings),
    store: DocumentStore = Depends(get_document_store),
    results: ResultStore = Depends(get_result_store),
    llm_factory: Callable[[], LlmClient] = Depends(get_llm_factory),
) -> TranslatedContinuation:
    """Translate the saved English continuation insights (and save the translation)."""
    _get_ready_record(doc_id, store)
    language = _language(lang)
    source = _source(doc_id, results)
    if language.code == "en":
        return english_continuation(source, language)
    llm = _llm(llm_factory)
    try:
        result = translate_continuation(source, language, llm, settings.translation_batch_size)
    except LlmError as exc:
        raise exc.to_app_error() from exc
    results.save(doc_id, f"continuation.{language.code}", result.model_dump(mode="json"))
    return result


@router.get(
    "/{doc_id}/continuation/{lang}", response_model=TranslatedContinuation, responses=ERRORS_READY
)
def get_continuation_translation(
    doc_id: DocId,
    lang: LangCode,
    store: DocumentStore = Depends(get_document_store),
    results: ResultStore = Depends(get_result_store),
) -> TranslatedContinuation:
    """The last saved translation (no model call). `stale` is true if the English was regenerated since."""
    _get_ready_record(doc_id, store)
    language = _language(lang)
    source = _source(doc_id, results)
    if language.code == "en":
        return english_continuation(source, language)
    saved = results.load(doc_id, f"continuation.{language.code}")
    if saved is None:
        raise NotFoundError(
            f"These insights have not been translated into {language.name} yet. "
            f"Use POST /continuation/{language.code}.",
            code="not_generated",
        )
    translated = TranslatedContinuation.model_validate(saved)
    translated.stale = translated.source_generated_at != source.generated_at
    return translated
