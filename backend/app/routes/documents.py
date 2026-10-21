"""Document routes: upload, status, extracted text, preview and delete."""
import logging
import uuid
from typing import Annotated, Callable, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Path,
    Query,
    Response,
    UploadFile,
)
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.schemas.common import ErrorResponse
from app.schemas.documents import (
    DocumentList,
    DocumentPreview,
    DocumentRecord,
    DocumentStatus,
    PageInfo,
    PageList,
    PageText,
)
from app.services.document_pipeline import process_document
from app.services.document_store import DocumentStore, get_document_store
from app.services.embedder import Embedder, get_embedder_factory
from app.services.index_store import IndexStore, get_index_store
from app.services.ocr import OcrEngine, get_ocr_engine
from app.services.page_store import PageStore, get_page_store
from app.services.preview import build_preview
from app.services.results_store import ResultStore, get_result_store
from app.services.upload_service import (
    pdf_path_for,
    require_pdf_extension,
    sanitize_filename,
    save_upload,
    validate_pdf,
)
from app.utils.errors import ConflictError, NotFoundError, StorageError
from app.utils.files import remove_quietly

logger = logging.getLogger("legal-ai.documents")

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

# Ids are 32 hex characters. Rejecting anything else early also means an id
# can never be used to point at some other file on disk.
DocId = Annotated[
    str, Path(pattern=r"^[a-f0-9]{32}$", description="Document identifier")
]

ERRORS_READ = {
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}
ERRORS_READY = {**ERRORS_READ, 409: {"model": ErrorResponse}}


def get_ocr_factory() -> Callable[[], Optional[OcrEngine]]:
    """A dependency, so tests can swap the OCR engine for a fake one."""
    return get_ocr_engine


def _get_record(doc_id: str, store: DocumentStore) -> DocumentRecord:
    record = store.get(doc_id)
    if record is None:
        raise NotFoundError(f"Document '{doc_id}' was not found.")
    return record


def _get_ready_record(doc_id: str, store: DocumentStore) -> DocumentRecord:
    record = _get_record(doc_id, store)
    if record.status == DocumentStatus.failed:
        raise ConflictError(
            record.error or "Processing this document failed.",
            code="processing_failed",
        )
    if record.status != DocumentStatus.ready:
        raise ConflictError(
            "This document is still being processed. Please try again shortly.",
            code="not_ready",
        )
    return record


@router.post(
    "",
    response_model=DocumentRecord,
    status_code=202,
    responses={
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def upload_document(
    response: Response,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="A court judgment as a PDF file."),
    settings: Settings = Depends(get_settings),
    store: DocumentStore = Depends(get_document_store),
    page_store: PageStore = Depends(get_page_store),
    ocr_factory: Callable[[], Optional[OcrEngine]] = Depends(get_ocr_factory),
    index_store: IndexStore = Depends(get_index_store),
    embedder_factory: Callable[[], Embedder] = Depends(get_embedder_factory),
) -> DocumentRecord:
    """Upload a judgment PDF.

    The file is checked straight away (type, size, readable, not encrypted).
    If it passes, text extraction continues in the background and this returns
    202 with status "processing". Poll `GET /api/v1/documents/{id}` until the
    status is "ready" or "failed".
    """
    filename = sanitize_filename(file.filename)
    require_pdf_extension(filename)

    doc_id = uuid.uuid4().hex
    pdf_path = pdf_path_for(settings, doc_id)
    size = await save_upload(file, pdf_path, settings.max_upload_mb * 1024 * 1024)
    try:
        page_count = await run_in_threadpool(validate_pdf, pdf_path, settings.max_pages)
        record = store.add(
            filename,
            doc_id=doc_id,
            status=DocumentStatus.processing,
            page_count=page_count,
            size_bytes=size,
        )
    except Exception:
        remove_quietly(pdf_path)  # never keep a file we rejected
        raise

    background_tasks.add_task(
        process_document,
        doc_id,
        store=store,
        page_store=page_store,
        settings=settings,
        get_ocr_engine=ocr_factory,
        index_store=index_store,
        get_embedder=embedder_factory,
    )
    response.headers["Location"] = f"/api/v1/documents/{doc_id}"
    logger.info("Accepted upload %s (%s, %d pages, %d bytes)", doc_id, filename, page_count, size)
    return record


@router.get(
    "",
    response_model=DocumentList,
    responses={500: {"model": ErrorResponse}},
)
def list_documents(
    store: DocumentStore = Depends(get_document_store),
) -> DocumentList:
    """All uploaded documents, newest first."""
    records = store.list()
    return DocumentList(documents=records, total=len(records))


@router.get("/{doc_id}", response_model=DocumentRecord, responses=ERRORS_READ)
def get_document(
    doc_id: DocId, store: DocumentStore = Depends(get_document_store)
) -> DocumentRecord:
    """One document's filename, status, progress and warnings."""
    return _get_record(doc_id, store)


@router.get(
    "/{doc_id}/preview", response_model=DocumentPreview, responses=ERRORS_READY
)
def preview_document(
    doc_id: DocId,
    chars: Annotated[int, Query(ge=200, le=20000, description="Approximate length.")] = 3000,
    store: DocumentStore = Depends(get_document_store),
    page_store: PageStore = Depends(get_page_store),
) -> DocumentPreview:
    """The opening text of the judgment, with "[Page N]" markers."""
    record = _get_ready_record(doc_id, store)
    preview, truncated = build_preview(page_store.load(doc_id), chars)
    return DocumentPreview(
        document_id=doc_id,
        filename=record.filename,
        page_count=record.page_count or 0,
        preview=preview,
        truncated=truncated,
        chars_returned=len(preview),
    )


@router.get("/{doc_id}/pages", response_model=PageList, responses=ERRORS_READY)
def list_pages(
    doc_id: DocId,
    store: DocumentStore = Depends(get_document_store),
    page_store: PageStore = Depends(get_page_store),
) -> PageList:
    """Every page with how its text was read (text, ocr or empty), without the text."""
    _get_ready_record(doc_id, store)
    pages = page_store.load(doc_id)
    infos = [PageInfo(**page.model_dump(exclude={"text"})) for page in pages]
    return PageList(document_id=doc_id, pages=infos, total=len(infos))


@router.get(
    "/{doc_id}/pages/{page_number}", response_model=PageText, responses=ERRORS_READY
)
def get_page(
    doc_id: DocId,
    page_number: Annotated[int, Path(ge=1, description="Physical PDF page, from 1.")],
    store: DocumentStore = Depends(get_document_store),
    page_store: PageStore = Depends(get_page_store),
) -> PageText:
    """The full text of one page."""
    _get_ready_record(doc_id, store)
    for page in page_store.load(doc_id):
        if page.page_number == page_number:
            return page
    raise NotFoundError(f"Page {page_number} does not exist in this document.")


@router.delete(
    "/{doc_id}",
    status_code=204,
    response_class=Response,
    responses=ERRORS_READ,
)
def delete_document(
    doc_id: DocId,
    settings: Settings = Depends(get_settings),
    store: DocumentStore = Depends(get_document_store),
    page_store: PageStore = Depends(get_page_store),
    index_store: IndexStore = Depends(get_index_store),
    results: ResultStore = Depends(get_result_store),
) -> Response:
    """Delete a document: its PDF, its extracted text and its record.

    Judgments can be sensitive, so the files go first; the record is removed
    only once the files are gone.
    """
    _get_record(doc_id, store)
    try:
        pdf_path_for(settings, doc_id).unlink(missing_ok=True)
    except OSError as exc:
        logger.error("Cannot delete PDF for %s: %s", doc_id, exc)
        raise StorageError("The uploaded file could not be deleted.") from exc
    page_store.delete(doc_id)
    index_store.delete(doc_id)
    results.delete_all(doc_id)
    store.delete(doc_id)
    return Response(status_code=204)
