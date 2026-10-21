import pytest

from app.schemas.documents import PageMethod, PageText
from app.services.chunker import chunk_pages, clean_page, find_repeated_lines


def page(n, text):
    return PageText(page_number=n, text=text, method=PageMethod.text)


def scr_pages(count=8):
    """Pages shaped like a law-report PDF: running header, margin letters, page number."""
    pages = []
    for n in range(1, count + 1):
        words = ["land", "tenancy", "bail", "contract", "tax", "murder", "easement", "writ", "dowry", "lease"]
        filler = "\n".join(f"Paragraph {k}: the {words[(n + k) % 10]} dispute of {words[(n * k + 3) % 10]} parties continued." for k in range(5))
        body = (
            f"A\nThe petitioner argued point number {n} about the right to privacy.\n"
            f"B\nThe Court considered the argument {n} and examined earlier decisions carefully.\n{filler}"
        )
        pages.append(page(n, f"{569 + n} SUPREME COURT REPORTS [2017] 10 S.C.R.\n{body}\n{569 + n}"))
    return pages


def test_running_headers_are_detected():
    repeated = find_repeated_lines(scr_pages())
    assert any("SUPREME COURT REPORTS" in shape for shape in repeated)


def test_cleaning_removes_header_margin_letters_and_page_numbers():
    pages = scr_pages()
    cleaned = clean_page(pages[3].text, find_repeated_lines(pages))
    assert "SUPREME COURT REPORTS" not in cleaned
    assert " A " not in f" {cleaned} " and " B " not in f" {cleaned} "
    assert not cleaned.endswith("573")
    assert "right to privacy" in cleaned


def test_cleaning_keeps_real_numbers_in_body_text():
    text = "Header line\nThe appeal was filed in 2017.\n42 petitioners joined.\nFooter"
    cleaned = clean_page(text, set())
    assert "2017" in cleaned and "42 petitioners" in cleaned


def test_short_pages_never_lose_body_lines_as_headers():
    pages = [page(n, f"Body sentence {n}.\nAnother line {n}.\nThird line {n}.") for n in range(1, 9)]
    assert find_repeated_lines(pages) == set()
    assert "Another line 3" in clean_page(pages[2].text, set())


def test_short_documents_never_lose_lines_as_headers():
    pages = [page(1, "Same line\nBody one."), page(2, "Same line\nBody two.")]
    assert find_repeated_lines(pages) == set()


def test_every_chunk_has_valid_pages_and_respects_size():
    chunks = chunk_pages(scr_pages(), chunk_size=300, chunk_overlap=60)
    assert chunks
    for chunk in chunks:
        assert 1 <= chunk.page_start <= chunk.page_end <= 8
        assert len(chunk.text) <= 300 + 60 + 5
    assert [c.chunk_id for c in chunks] == list(range(len(chunks)))


def test_chunk_pages_match_source_text():
    pages = scr_pages()
    chunks = chunk_pages(pages, 300, 60)
    mentions = [c for c in chunks if "point number 5" in c.text]
    assert mentions and all(c.page_start <= 5 <= c.page_end for c in mentions)


def test_overlap_repeats_text_between_neighbours():
    chunks = chunk_pages(scr_pages(), chunk_size=300, chunk_overlap=120)
    shared = 0
    for a, b in zip(chunks, chunks[1:]):
        last_sentence = a.text.split(". ")[-1]
        if last_sentence[:30] in b.text:
            shared += 1
    assert shared > 0


def test_no_text_is_lost():
    pages = scr_pages()
    joined = " ".join(c.text for c in chunk_pages(pages, 300, 60))
    for n in range(1, 9):
        assert f"point number {n}" in joined
        assert f"argument {n}" in joined


def test_very_long_sentence_is_split():
    long_text = "word " * 600  # one 3000-character 'sentence', no punctuation
    chunks = chunk_pages([page(1, long_text)], chunk_size=500, chunk_overlap=50)
    assert len(chunks) >= 6
    assert all(len(c.text) <= 560 for c in chunks)


def test_blank_pages_give_no_chunks():
    assert chunk_pages([page(1, ""), page(2, "   ")], 500, 50) == []


@pytest.mark.parametrize("size,overlap", [(50, 0), (500, 250), (500, -1)])
def test_bad_settings_are_rejected(size, overlap):
    with pytest.raises(ValueError):
        chunk_pages([page(1, "text")], size, overlap)
