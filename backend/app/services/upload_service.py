"""Receiving an uploaded PDF safely: name, size, type and openability checks.

Nothing from the user is ever used as a path on disk. The file is stored as
"<random id>.pdf"; the original name is kept only as a label in the registry.
"""
import logging
import re
from pathlib import Path
from typing import Optional

import pymupdf
from fastapi import UploadFile

from app.config import Settings
from app.utils.errors import (
    PayloadTooLargeError,
    UnprocessableFileError,
    UnsupportedMediaTypeError,
)
from app.utils.files import remove_quietly

logger = logging.getLogger("legal-ai.upload")

CHUNK_SIZE = 1024 * 1024
PDF_MAGIC = b"%PDF-"
DEFAULT_NAME = "judgment.pdf"


def pdf_path_for(settings: Settings, doc_id: str) -> Path:
    """Where the original PDF is stored. Only ever built from a generated id."""
    return settings.upload_path / f"{doc_id}.pdf"


def sanitize_filename(name: Optional[str]) -> str:
    """Keep just a display name: no folders, no control characters, bounded length."""
    if not name:
        return DEFAULT_NAME
    base = re.split(r"[\\/]", name)[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()[:150]
    return base or DEFAULT_NAME


def require_pdf_extension(filename: str) -> None:
    if not filename.lower().endswith(".pdf"):
        raise UnsupportedMediaTypeError(
            "Only PDF files are supported. Please upload a file ending in .pdf."
        )


async def save_upload(upload: UploadFile, destination: Path, max_bytes: int) -> int:
    """Stream the upload to disk, refusing anything over `max_bytes`.

    Reads in 1 MB pieces, so a huge upload is rejected as soon as it crosses
    the limit instead of being loaded fully into memory. Returns the size in
    bytes. A partly written file is removed on any failure.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    checked_header = False
    try:
        with destination.open("wb") as out:
            while True:
                chunk = await upload.read(CHUNK_SIZE)
                if not chunk:
                    break
                if not checked_header:
                    if PDF_MAGIC not in chunk[:1024]:
                        raise UnsupportedMediaTypeError(
                            "This file is not a PDF, even though its name ends in .pdf.",
                            code="not_a_pdf",
                        )
                    checked_header = True
                size += len(chunk)
                if size > max_bytes:
                    raise PayloadTooLargeError(
                        f"The file is larger than the {max_bytes / (1024 * 1024):g} MB limit."
                    )
                out.write(chunk)
        if size == 0:
            raise UnprocessableFileError("The file is empty.", code="empty_file")
    except BaseException:
        remove_quietly(destination)
        raise
    return size


def validate_pdf(path: Path, max_pages: int) -> int:
    """Open the PDF to be sure it is usable. Returns its page count.

    The file is opened from memory, not from its path. When PyMuPDF fails to
    open a corrupt file by path it leaves the file open, and on Windows an open
    file cannot be deleted, so rejecting the upload would crash with
    PermissionError instead of explaining the problem.
    """
    try:
        data = path.read_bytes()
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                raise UnprocessableFileError(
                    "This PDF is password-protected. Remove the password and upload it again.",
                    code="encrypted_pdf",
                )
            page_count = doc.page_count
    except UnprocessableFileError:
        raise
    except Exception as exc:  # PyMuPDF raises several different error types
        logger.warning("PDF could not be opened: %s", exc)
        raise UnprocessableFileError(
            "This PDF could not be opened. The file may be corrupted.",
            code="invalid_pdf",
        ) from exc

    if page_count == 0:
        raise UnprocessableFileError("This PDF has no pages.", code="invalid_pdf")
    if page_count > max_pages:
        raise UnprocessableFileError(
            f"This PDF has {page_count} pages; the limit is {max_pages}.",
            code="too_many_pages",
        )
    return page_count
