"""Load judgments from PDFs for evaluation, using the same code the app uses.

The extraction, cleaning and chunking calls are the application's own, so an
evaluation measures the real pipeline and not a lookalike. A document's id is
the first 32 hex characters of its file's SHA-256, so the same PDF always has
the same id and a changed file cannot be mistaken for the old one.
"""
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.config import Settings
from app.schemas.documents import PageText
from app.schemas.search import Chunk
from app.services.chunker import chunk_pages, clean_pages
from app.services.pdf_extractor import extract_pdf


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@dataclass
class Corpus:
    name: str  # PDF file name without extension
    path: Path
    sha256: str
    doc_id: str
    pages: list[PageText]
    cleaned: dict[int, str]
    chunks: list[Chunk]
    ocr_pages: int
    empty_pages: int
    warnings: list[str]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def describe(self) -> dict:
        chars = [len(p.text) for p in self.pages]
        return {
            "name": self.name,
            "file": self.path.name,
            "sha256": self.sha256,
            "pages": self.page_count,
            "characters": sum(chars),
            "ocr_pages": self.ocr_pages,
            "empty_pages": self.empty_pages,
            "chunks": len(self.chunks),
            "warnings": self.warnings,
        }


def load_corpus(
    pdf: Path,
    settings: Settings,
    *,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    get_ocr_engine: Optional[Callable] = None,
) -> Corpus:
    pdf = Path(pdf)
    digest = file_sha256(pdf)
    result = extract_pdf(
        pdf,
        get_ocr_engine=get_ocr_engine,
        ocr_dpi=settings.ocr_dpi,
        ocr_min_chars=settings.ocr_min_chars,
    )
    size = chunk_size or settings.chunk_size
    overlap = settings.chunk_overlap if chunk_overlap is None else chunk_overlap
    return Corpus(
        name=pdf.stem,
        path=pdf,
        sha256=digest,
        doc_id=digest[:32],
        pages=result.pages,
        cleaned=clean_pages(result.pages),
        chunks=chunk_pages(result.pages, size, overlap),
        ocr_pages=result.ocr_pages,
        empty_pages=result.empty_pages,
        warnings=list(result.warnings),
    )


def find_pdfs(folder: Path) -> list[Path]:
    return sorted(Path(folder).glob("*.pdf"), key=lambda p: p.name.lower())
