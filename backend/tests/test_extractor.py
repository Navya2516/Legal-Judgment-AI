import pytest

from app.schemas.documents import PageMethod
from app.services.pdf_extractor import clean_text, extract_pdf
from tests import pdf_factory
from tests.conftest import FakeOcr


def test_text_pdf_keeps_page_numbers_and_text(text_pdf):
    result = extract_pdf(text_pdf)
    assert [page.page_number for page in result.pages] == [1, 2, 3]
    assert all(page.method == PageMethod.text for page in result.pages)
    assert "Article 368" in result.pages[1].text
    assert "basic structure" in result.pages[2].text
    assert result.ocr_pages == 0
    assert result.warnings == []


def test_text_pdf_never_loads_the_ocr_engine(text_pdf):
    def explode():
        raise AssertionError("OCR must not be loaded for a text PDF")

    extract_pdf(text_pdf, get_ocr_engine=explode)


def test_scanned_pdf_uses_ocr_on_every_page(scanned_pdf):
    ocr = FakeOcr("This text came from the OCR engine for a scanned page.")
    result = extract_pdf(scanned_pdf, get_ocr_engine=lambda: ocr)
    assert ocr.calls == 3
    assert all(page.method == PageMethod.ocr for page in result.pages)
    assert result.pages[0].text.startswith("This text came from the OCR engine")
    assert any("OCR" in warning for warning in result.warnings)


def test_mixed_pdf_only_ocrs_the_scanned_page(tmp_path):
    path = pdf_factory.make_mixed_pdf(tmp_path / "mixed.pdf")
    ocr = FakeOcr("Recognised scanned page text, long enough to count as real text.")
    result = extract_pdf(path, get_ocr_engine=lambda: ocr)
    assert [page.method for page in result.pages] == [
        PageMethod.text,
        PageMethod.ocr,
        PageMethod.text,
    ]
    assert ocr.calls == 1


def test_scanned_pdf_without_ocr_reports_unread_pages(scanned_pdf):
    result = extract_pdf(scanned_pdf, get_ocr_engine=lambda: None)
    assert result.char_count == 0
    assert result.unread_scan_pages == [1, 2, 3]
    assert all(page.method == PageMethod.empty for page in result.pages)
    assert any("OCR is not available" in warning for warning in result.warnings)


def test_ocr_failure_on_one_page_does_not_stop_the_rest(tmp_path):
    path = pdf_factory.make_scanned_pdf(tmp_path / "scan.pdf")

    class FlakyOcr(FakeOcr):
        def recognize(self, image):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("engine crashed")
            return "Good OCR text that is comfortably longer than the minimum."

    result = extract_pdf(path, get_ocr_engine=lambda: FlakyOcr())
    assert [page.method for page in result.pages] == [
        PageMethod.ocr,
        PageMethod.empty,
        PageMethod.ocr,
    ]
    assert any("OCR failed on 1 page" in warning for warning in result.warnings)


def test_blank_pages_are_marked_empty_without_ocr(tmp_path):
    path = pdf_factory.make_blank_pdf(tmp_path / "blank.pdf")
    result = extract_pdf(path, get_ocr_engine=lambda: FakeOcr())
    assert result.char_count == 0
    assert result.empty_pages == 2
    assert result.unread_scan_pages == []  # no image, so not a scan


def test_progress_callback_reports_each_page(text_pdf):
    seen = []
    extract_pdf(text_pdf, on_progress=lambda done, total: seen.append((done, total)))
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_clean_text_normalises_without_changing_words():
    raw = "conﬁrmed  the\xa0order\x00.\r\n\r\n\r\n\r\nSee ex-\nofficio\xad."
    cleaned = clean_text(raw)
    assert cleaned == "confirmed the order.\n\nSee ex-\nofficio."


@pytest.mark.skipif(
    pytest.importorskip("rapidocr", reason="rapidocr not installed") is None,
    reason="rapidocr not installed",
)
def test_real_ocr_reads_a_scanned_page(scanned_pdf):
    """End to end with the real OCR engine (skipped when it is not installed)."""
    from app.services.ocr import RapidOcrEngine

    engine = RapidOcrEngine()
    result = extract_pdf(scanned_pdf, get_ocr_engine=lambda: engine)
    assert all(page.method == PageMethod.ocr for page in result.pages)
    assert "Article 368" in result.pages[1].text
    assert "basic structure" in result.pages[2].text
