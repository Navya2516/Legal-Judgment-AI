"""Runs after upload: extract the text, save it, and keep the status current.

This runs in the background, so the upload request returns immediately and
the frontend polls the document's status. Every failure ends in a "failed"
status with a plain-language reason, never a document stuck in "processing".
"""
import logging
from typing import Callable, Optional

from app.config import Settings
from app.services.document_store import DocumentStore
from app.services.embedder import Embedder
from app.services.index_store import IndexStore
from app.services.indexing import build_document_index
from app.services.ocr import OcrEngine
from app.services.page_store import PageStore
from app.services.pdf_extractor import extract_pdf
from app.services.upload_service import pdf_path_for

logger = logging.getLogger("legal-ai.pipeline")

PROGRESS_EVERY = 10  # pages between progress updates written to the registry


def process_document(
    doc_id: str,
    *,
    store: DocumentStore,
    page_store: PageStore,
    settings: Settings,
    get_ocr_engine: Optional[Callable[[], Optional[OcrEngine]]] = None,
    index_store: Optional[IndexStore] = None,
    get_embedder: Optional[Callable[[], Embedder]] = None,
) -> None:
    if store.get(doc_id) is None:
        return

    last_reported = 0

    def report(done: int, total: int) -> None:
        nonlocal last_reported
        if done == total or done - last_reported >= PROGRESS_EVERY:
            store.update(doc_id, pages_processed=done)
            last_reported = done

    try:
        result = extract_pdf(
            pdf_path_for(settings, doc_id),
            get_ocr_engine=get_ocr_engine,
            ocr_dpi=settings.ocr_dpi,
            ocr_min_chars=settings.ocr_min_chars,
            on_progress=report,
        )

        if result.char_count == 0:
            if result.unread_scan_pages:
                reason = (
                    "This looks like a scanned document, but OCR is not available, so "
                    "no text could be read. Install OCR support (see the README) and "
                    "upload the file again."
                )
            else:
                reason = "No readable text was found in this PDF."
            store.update(
                doc_id, status="failed", error=reason, warnings=result.warnings
            )
            return

        page_store.save(doc_id, result.pages)
        updated = store.update(
            doc_id,
            status="ready",
            error=None,
            pages_processed=len(result.pages),
            ocr_pages=result.ocr_pages,
            empty_pages=result.empty_pages,
            char_count=result.char_count,
            warnings=result.warnings,
        )
        if updated is None:  # the document was deleted while it was processing
            page_store.delete(doc_id)
            return
        # The text is usable now; the search index is built as a second step and
        # its failure never undoes a successful extraction.
        if index_store is not None and get_embedder is not None:
            build_document_index(
                doc_id,
                store=store,
                page_store=page_store,
                index_store=index_store,
                settings=settings,
                get_embedder=get_embedder,
            )
        logger.info(
            "Processed %s: %d pages, %d via OCR, %d empty",
            doc_id,
            len(result.pages),
            result.ocr_pages,
            result.empty_pages,
        )
    except Exception:
        logger.exception("Processing failed for %s", doc_id)
        try:
            store.update(
                doc_id,
                status="failed",
                error="The text could not be extracted from this PDF.",
            )
        except Exception:
            logger.exception("Could not record the failure for %s", doc_id)
