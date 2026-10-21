"""Schemas describing uploaded judgments, their processing state and their text."""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field


class DocumentStatus(str, Enum):
    uploaded = "uploaded"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class PageMethod(str, Enum):
    """How the text of a page was obtained."""

    text = "text"  # selectable text stored in the PDF
    ocr = "ocr"  # read from a scanned image by OCR
    empty = "empty"  # nothing could be read from the page


class DocumentRecord(BaseModel):
    id: str
    filename: str
    status: DocumentStatus = DocumentStatus.uploaded
    page_count: Optional[int] = None
    pages_processed: int = 0
    size_bytes: Optional[int] = None
    char_count: Optional[int] = None
    ocr_pages: int = 0
    empty_pages: int = 0
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
    error: Optional[str] = None
    # Search index (Phase 4). Built after text extraction; the text is usable
    # (status "ready") even while the index is still being built.
    index_status: str = "none"  # none | indexing | ready | failed
    chunk_count: int = 0
    index_error: Optional[str] = None


class DocumentList(BaseModel):
    documents: list[DocumentRecord]
    total: int


class PageText(BaseModel):
    """The text of one page. `page_number` is the physical PDF page, from 1."""

    page_number: int = Field(ge=1)
    text: str
    method: PageMethod

    @computed_field  # type: ignore[prop-decorator]
    @property
    def char_count(self) -> int:
        return len(self.text)


class PageInfo(BaseModel):
    page_number: int
    method: PageMethod
    char_count: int


class PageList(BaseModel):
    document_id: str
    pages: list[PageInfo]
    total: int


class DocumentPreview(BaseModel):
    document_id: str
    filename: str
    page_count: int
    preview: str
    truncated: bool
    chars_returned: int
