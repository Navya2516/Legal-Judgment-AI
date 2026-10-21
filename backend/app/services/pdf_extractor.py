"""Read text from a PDF page by page, falling back to OCR for scanned pages.

Page numbers are the PDF's own page positions (1 = first page of the file).
Many judgments also print their own page numbers, and those can differ from
the PDF position (for example, an unnumbered cover page). Citations in this
system always use the PDF position, so a user can jump straight to that page
in any PDF viewer.

A page is sent to OCR only when it has too little real text AND contains an
image, so ordinary text PDFs never load the (slow) OCR engine at all.
"""
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pymupdf

from app.schemas.documents import PageMethod, PageText
from app.services.ocr import OcrEngine

logger = logging.getLogger("legal-ai.pdf")

REPLACEMENT_CHAR = "�"
GARBLED_THRESHOLD = 0.02  # warn when more than 2% of characters are unreadable

_SPACES = re.compile(r"[ \t]+")
_EXTRA_BLANK_LINES = re.compile(r"\n{3,}")


def clean_text(raw: str) -> str:
    """Tidy extracted text without changing any words.

    Ligatures (such as "fi") and non-breaking spaces become plain characters,
    control characters and soft hyphens are dropped, and runs of spaces and
    blank lines are collapsed. Hyphenated line breaks are deliberately NOT
    re-joined: in legal text that could merge words wrongly (for example
    "ex-officio"), and every word must stay exactly as the court wrote it.
    """
    text = unicodedata.normalize("NFKC", raw)
    text = text.replace("\x00", "").replace("­", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _EXTRA_BLANK_LINES.sub("\n\n", text).strip()


@dataclass
class ExtractionResult:
    pages: list[PageText]
    warnings: list[str] = field(default_factory=list)
    unread_scan_pages: list[int] = field(default_factory=list)

    @property
    def ocr_pages(self) -> int:
        return sum(1 for page in self.pages if page.method == PageMethod.ocr)

    @property
    def empty_pages(self) -> int:
        return sum(1 for page in self.pages if page.method == PageMethod.empty)

    @property
    def char_count(self) -> int:
        return sum(len(page.text) for page in self.pages)


def _alnum_count(text: str) -> int:
    return sum(1 for ch in text if ch.isalnum())


def _render_bgr(page: "pymupdf.Page", dpi: int) -> np.ndarray:
    """Render a page to a BGR image (height x width x 3, uint8) for the OCR engine."""
    pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    rgb = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width, 3
    )
    return np.ascontiguousarray(rgb[:, :, ::-1])


def extract_pdf(
    path: Path,
    *,
    get_ocr_engine: Optional[Callable[[], Optional[OcrEngine]]] = None,
    ocr_dpi: int = 200,
    ocr_min_chars: int = 40,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> ExtractionResult:
    """Extract every page's text. `get_ocr_engine` is only called if a page needs OCR."""
    engine_state: dict = {"loaded": False, "engine": None}

    def engine() -> Optional[OcrEngine]:
        if not engine_state["loaded"]:
            engine_state["engine"] = get_ocr_engine() if get_ocr_engine else None
            engine_state["loaded"] = True
        return engine_state["engine"]

    pages: list[PageText] = []
    unread: list[int] = []
    ocr_failures = 0
    bad_pages = 0

    with pymupdf.open(path) as document:
        total = document.page_count
        for index in range(total):
            number = index + 1
            text = ""
            method = PageMethod.empty
            try:
                page = document.load_page(index)
                text = clean_text(page.get_text("text", sort=True))
                method = PageMethod.text if text else PageMethod.empty

                if _alnum_count(text) < ocr_min_chars and page.get_images():
                    ocr = engine()
                    if ocr is None:
                        if not text:
                            unread.append(number)
                    else:
                        try:
                            ocr_text = clean_text(ocr.recognize(_render_bgr(page, ocr_dpi)))
                        except Exception as exc:
                            ocr_failures += 1
                            logger.warning("OCR failed on page %d: %s", number, exc)
                            ocr_text = ""
                        if _alnum_count(ocr_text) > _alnum_count(text):
                            text, method = ocr_text, PageMethod.ocr
            except Exception as exc:
                bad_pages += 1
                logger.warning("Cannot read page %d: %s", number, exc)
                text, method = "", PageMethod.empty

            pages.append(PageText(page_number=number, text=text, method=method))
            if on_progress:
                on_progress(number, total)

    result = ExtractionResult(pages=pages, unread_scan_pages=unread)

    if unread:
        result.warnings.append(
            f"{len(unread)} page(s) look like scans, but OCR is not available, "
            "so their text could not be read."
        )
    if ocr_failures:
        result.warnings.append(f"OCR failed on {ocr_failures} page(s).")
    if bad_pages:
        result.warnings.append(f"{bad_pages} page(s) could not be read from the PDF.")
    if result.ocr_pages:
        result.warnings.append(
            f"{result.ocr_pages} page(s) were read with OCR and may contain "
            "recognition errors. Check important details against the original."
        )
    garbled = sum(page.text.count(REPLACEMENT_CHAR) for page in pages)
    if result.char_count and garbled / result.char_count > GARBLED_THRESHOLD:
        result.warnings.append(
            "Some text contains unreadable characters. The PDF may use a font "
            "encoding that cannot be extracted reliably."
        )
    return result
