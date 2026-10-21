"""Builds small PDFs for tests, so no real judgment is needed in the repository."""
from pathlib import Path

import pymupdf

PAGE_TEXTS = [
    "IN THE SUPREME COURT OF INDIA. CIVIL ORIGINAL JURISDICTION. "
    "Writ Petition (Civil) No. 135 of 1970. Petitioner versus State of Kerala.",
    "Article 368 of the Constitution of India deals with the power of Parliament "
    "to amend the Constitution and the procedure for doing so.",
    "The court held that the basic structure of the Constitution cannot be "
    "amended. The petition is allowed in part, with no order as to costs.",
]


def make_text_pdf(path: Path, pages: list[str] = PAGE_TEXTS) -> Path:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(72, 72, 520, 760), text, fontsize=12)
    doc.save(path)
    doc.close()
    return path


def make_scanned_pdf(path: Path, pages: list[str] = PAGE_TEXTS) -> Path:
    """An image-only PDF: each page is a picture of text, with no text layer."""
    doc = pymupdf.open()
    for text in pages:
        source = pymupdf.open()
        source_page = source.new_page()
        source_page.insert_textbox(pymupdf.Rect(72, 72, 520, 760), text, fontsize=14)
        pixmap = source_page.get_pixmap(dpi=150)
        page = doc.new_page(width=source_page.rect.width, height=source_page.rect.height)
        page.insert_image(page.rect, pixmap=pixmap)
        source.close()
    doc.save(path)
    doc.close()
    return path


def make_blank_pdf(path: Path, pages: int = 2) -> Path:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(path)
    doc.close()
    return path


def make_encrypted_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "secret judgment text " * 5)
    doc.save(
        path,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
    )
    doc.close()
    return path


def make_mixed_pdf(path: Path) -> Path:
    """Page 1 has real text, page 2 is a scan, page 3 has real text."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(72, 72, 520, 760), PAGE_TEXTS[0], fontsize=12)

    source = pymupdf.open()
    sp = source.new_page()
    sp.insert_textbox(pymupdf.Rect(72, 72, 520, 760), PAGE_TEXTS[1], fontsize=14)
    scan = doc.new_page(width=sp.rect.width, height=sp.rect.height)
    scan.insert_image(scan.rect, pixmap=sp.get_pixmap(dpi=150))
    source.close()

    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(72, 72, 520, 760), PAGE_TEXTS[2], fontsize=12)
    doc.save(path)
    doc.close()
    return path
