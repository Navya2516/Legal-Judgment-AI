"""Ask a question about a judgment and get a page-cited answer."""
import logging
from typing import Callable

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.routes.analysis import ERRORS_LLM, _llm
from app.routes.documents import DocId, _get_ready_record
from app.routes.retrieval import _require_index
from app.routes.translation import _language
from app.schemas.ask import AskRequest, AskResponse
from app.services.ask import answer_question
from app.services.document_store import DocumentStore, get_document_store
from app.services.embedder import Embedder, get_embedder_factory
from app.services.index_store import IndexStore, get_index_store
from app.services.llm import LlmClient, LlmError, get_llm_factory
from app.services.page_store import PageStore, get_page_store

logger = logging.getLogger("legal-ai.ask")

router = APIRouter(prefix="/api/v1/documents", tags=["ask"])


@router.post("/{doc_id}/ask", response_model=AskResponse, responses=ERRORS_LLM)
def ask_question(
    doc_id: DocId,
    body: AskRequest,
    settings: Settings = Depends(get_settings),
    store: DocumentStore = Depends(get_document_store),
    page_store: PageStore = Depends(get_page_store),
    index_store: IndexStore = Depends(get_index_store),
    llm_factory: Callable[[], LlmClient] = Depends(get_llm_factory),
    embedder_factory: Callable[[], Embedder] = Depends(get_embedder_factory),
) -> AskResponse:
    """Answer a question using only passages of this judgment.

    Every sentence carries page numbers and a word-for-word quote that the
    server has checked against the judgment. If the judgment does not answer
    the question, `answered` is false. Answers are not stored.
    """
    language = _language(body.lang)
    _get_ready_record(doc_id, store)
    loaded = _require_index(doc_id, store, index_store, settings)
    llm = _llm(llm_factory)
    try:
        return answer_question(
            doc_id,
            body.question,
            pages=page_store.load(doc_id),
            loaded=loaded,
            embedder=embedder_factory(),
            llm=llm,
            settings=settings,
            language=language,
            top_k=body.top_k,
            batch_size=settings.translation_batch_size,
        )
    except LlmError as exc:
        raise exc.to_app_error() from exc
