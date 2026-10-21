"""Translation routes: the summary and provision explanations in another language."""
import logging
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Path

from app.config import Settings, get_settings
from app.routes.analysis import ERRORS_LLM, _llm
from app.routes.documents import ERRORS_READY, DocId, _get_ready_record
from app.schemas.analysis import ProvisionExplanations, SummaryResult
from app.schemas.meta import Language
from app.schemas.translation import TranslatedProvisions, TranslatedSummary
from app.services.document_store import DocumentStore, get_document_store
from app.services.languages import SUPPORTED_LANGUAGES, get_language
from app.services.llm import LlmClient, LlmError, get_llm_factory
from app.services.results_store import ResultStore, get_result_store
from app.services.translation import (
    english_provisions,
    english_summary,
    translate_provisions,
    translate_summary,
)
from app.utils.errors import BadRequestError, NotFoundError

logger = logging.getLogger("legal-ai.translation")

router = APIRouter(prefix="/api/v1/documents", tags=["translation"])

LangCode = Annotated[
    str,
    Path(
        min_length=2,
        max_length=5,
        description="Language code: en, ta, hi, te, ml or kn (see GET /api/v1/languages).",
    ),
]


def _language(code: str) -> Language:
    language = get_language(code)
    if language is None:
        supported = ", ".join(lang.code for lang in SUPPORTED_LANGUAGES)
        raise BadRequestError(
            f"Language '{code}' is not supported. Supported codes: {supported}.",
            code="unsupported_language",
        )
    return language


def _source_summary(doc_id: str, results: ResultStore) -> SummaryResult:
    saved = results.load(doc_id, "summary")
    if saved is None:
        raise NotFoundError(
            "There is no English summary to translate yet. Generate it first with POST /summary.",
            code="not_generated",
        )
    return SummaryResult.model_validate(saved)


def _source_provisions(doc_id: str, results: ResultStore) -> ProvisionExplanations:
    saved = results.load(doc_id, "provisions")
    if saved is None:
        raise NotFoundError(
            "There are no English provision explanations to translate yet. "
            "Generate them first with POST /provisions/explain.",
            code="not_generated",
        )
    return ProvisionExplanations.model_validate(saved)


# ------------------------------------------------------------------ summary

@router.post(
    "/{doc_id}/summary/{lang}", response_model=TranslatedSummary, responses=ERRORS_LLM
)
def create_summary_translation(
    doc_id: DocId,
    lang: LangCode,
    settings: Settings = Depends(get_settings),
    store: DocumentStore = Depends(get_document_store),
    results: ResultStore = Depends(get_result_store),
    llm_factory: Callable[[], LlmClient] = Depends(get_llm_factory),
) -> TranslatedSummary:
    """Translate the saved English summary (and save the translation).

    Page numbers and the word-for-word quotes are copied from the English
    summary unchanged. Each translated sentence is checked (numbers kept, right
    script) and marked in `check`. English (`en`) needs no model call.
    """
    _get_ready_record(doc_id, store)
    language = _language(lang)
    source = _source_summary(doc_id, results)
    if language.code == "en":
        return english_summary(source, language)
    llm = _llm(llm_factory)
    try:
        result = translate_summary(source, language, llm, settings.translation_batch_size)
    except LlmError as exc:
        raise exc.to_app_error() from exc
    results.save(doc_id, f"summary.{language.code}", result.model_dump(mode="json"))
    return result


@router.get(
    "/{doc_id}/summary/{lang}", response_model=TranslatedSummary, responses=ERRORS_READY
)
def get_summary_translation(
    doc_id: DocId,
    lang: LangCode,
    store: DocumentStore = Depends(get_document_store),
    results: ResultStore = Depends(get_result_store),
) -> TranslatedSummary:
    """The last saved translation (no model call). `stale` is true if the English was regenerated since."""
    _get_ready_record(doc_id, store)
    language = _language(lang)
    source = _source_summary(doc_id, results)
    if language.code == "en":
        return english_summary(source, language)
    saved = results.load(doc_id, f"summary.{language.code}")
    if saved is None:
        raise NotFoundError(
            f"This summary has not been translated into {language.name} yet. Use POST /summary/{language.code}.",
            code="not_generated",
        )
    translated = TranslatedSummary.model_validate(saved)
    translated.stale = translated.source_generated_at != source.generated_at
    return translated


# --------------------------------------------------------------- provisions

@router.post(
    "/{doc_id}/provisions/explain/{lang}",
    response_model=TranslatedProvisions,
    responses=ERRORS_LLM,
)
def create_provisions_translation(
    doc_id: DocId,
    lang: LangCode,
    settings: Settings = Depends(get_settings),
    store: DocumentStore = Depends(get_document_store),
    results: ResultStore = Depends(get_result_store),
    llm_factory: Callable[[], LlmClient] = Depends(get_llm_factory),
) -> TranslatedProvisions:
    """Translate the saved English provision explanations (and save the translation)."""
    _get_ready_record(doc_id, store)
    language = _language(lang)
    source = _source_provisions(doc_id, results)
    if language.code == "en":
        return english_provisions(source, language)
    llm = _llm(llm_factory)
    try:
        result = translate_provisions(source, language, llm, settings.translation_batch_size)
    except LlmError as exc:
        raise exc.to_app_error() from exc
    results.save(doc_id, f"provisions.{language.code}", result.model_dump(mode="json"))
    return result


@router.get(
    "/{doc_id}/provisions/explain/{lang}",
    response_model=TranslatedProvisions,
    responses=ERRORS_READY,
)
def get_provisions_translation(
    doc_id: DocId,
    lang: LangCode,
    store: DocumentStore = Depends(get_document_store),
    results: ResultStore = Depends(get_result_store),
) -> TranslatedProvisions:
    """The last saved translation of the provision explanations (no model call)."""
    _get_ready_record(doc_id, store)
    language = _language(lang)
    source = _source_provisions(doc_id, results)
    if language.code == "en":
        return english_provisions(source, language)
    saved = results.load(doc_id, f"provisions.{language.code}")
    if saved is None:
        raise NotFoundError(
            f"These explanations have not been translated into {language.name} yet.",
            code="not_generated",
        )
    translated = TranslatedProvisions.model_validate(saved)
    translated.stale = translated.source_generated_at != source.generated_at
    return translated
