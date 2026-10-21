"""Turn page text into overlapping chunks that remember their page numbers.

Steps
1. Clean each page: drop running headers/footers (lines that repeat on many
   pages), bare page numbers and lone margin letters (A-H) used by law reports.
2. Split the cleaned text into sentences, never across a page boundary.
3. Pack sentences into chunks of about `chunk_size` characters. The last
   sentences of a chunk are repeated at the start of the next one (up to
   `chunk_overlap` characters) so an idea cut at a boundary is still found.

Each chunk records the first and last physical page it draws from, which is
what later phases cite.
"""
import re
from collections import Counter
from dataclasses import dataclass

from app.schemas.documents import PageText
from app.schemas.search import Chunk

CLEANING_VERSION = 1  # bump when cleaning/splitting rules change (marks indexes stale)

_EDGE_LINES = 2          # header/footer candidates: first and last N lines of a page
_MIN_PAGES_FOR_HEADERS = 4
_HEADER_SHARE = 0.25     # a line seen on >= 25% of pages is treated as a header/footer
_MAX_HEADER_LEN = 90
_PAGE_NUMBER = re.compile(r"^\d{1,4}$")
_MARGIN_LETTER = re.compile(r"^[A-H]$")
_SENTENCE_END = re.compile(r"(?<=[.;:?!])\s+(?=[A-Z0-9(\"'‘“\[])")
_MIN_CHUNK_CHARS = 30    # tiny trailing fragments are merged into the previous chunk


def _shape(line: str) -> str:
    """A line with digits masked, so '570 SUPREME COURT' matches '571 SUPREME COURT'."""
    return re.sub(r"\d+", "#", line.strip())


def find_repeated_lines(pages: list[PageText]) -> set[str]:
    """Shapes of short lines near page edges that repeat across many pages."""
    if len(pages) < _MIN_PAGES_FOR_HEADERS:
        return set()
    counts: Counter[str] = Counter()
    for page in pages:
        lines = [ln for ln in page.text.split("\n") if ln.strip()]
        if len(lines) <= 2 * _EDGE_LINES + 2:
            continue  # too short to tell a header from body text
        edge = lines[:_EDGE_LINES] + lines[-_EDGE_LINES:]
        counts.update({_shape(ln) for ln in edge if len(ln.strip()) <= _MAX_HEADER_LEN})
    threshold = max(3, int(len(pages) * _HEADER_SHARE))
    return {shape for shape, n in counts.items() if n >= threshold and shape.strip("# ")}


def clean_page(text: str, repeated: set[str]) -> str:
    lines = [ln.strip() for ln in text.split("\n")]
    nonblank = [i for i, ln in enumerate(lines) if ln]
    edges = set(nonblank[:_EDGE_LINES] + nonblank[-_EDGE_LINES:])
    kept: list[str] = []
    for i, line in enumerate(lines):
        if not line:
            continue
        if _MARGIN_LETTER.match(line):
            continue
        if i in edges and (
            _PAGE_NUMBER.match(line)
            or (len(line) <= _MAX_HEADER_LEN and _shape(line) in repeated)
        ):
            continue
        kept.append(line)
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


def clean_pages(pages: list[PageText]) -> dict[int, str]:
    """Cleaned, single-spaced text of every page, keyed by physical page number."""
    repeated = find_repeated_lines(pages)
    return {page.page_number: clean_page(page.text, repeated) for page in pages}


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]


def _hard_split(sentence: str, size: int) -> list[str]:
    """Break one over-long 'sentence' at word boundaries."""
    parts, current = [], ""
    for word in sentence.split(" "):
        while len(word) > size:  # a single enormous token: cut it
            if current:
                parts.append(current)
                current = ""
            parts.append(word[:size])
            word = word[size:]
        if current and len(current) + 1 + len(word) > size:
            parts.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        parts.append(current)
    return parts


@dataclass
class _Piece:
    text: str
    page: int


def chunk_pages(pages: list[PageText], chunk_size: int, chunk_overlap: int) -> list[Chunk]:
    if chunk_size < 100:
        raise ValueError("chunk_size must be at least 100 characters")
    if not 0 <= chunk_overlap < chunk_size // 2:
        raise ValueError("chunk_overlap must be at least 0 and less than half of chunk_size")

    repeated = find_repeated_lines(pages)
    pieces: list[_Piece] = []
    for page in pages:
        cleaned = clean_page(page.text, repeated)
        for sentence in split_sentences(cleaned):
            for part in _hard_split(sentence, chunk_size) if len(sentence) > chunk_size else [sentence]:
                pieces.append(_Piece(part, page.page_number))

    chunks: list[Chunk] = []

    def emit(group: list[_Piece]) -> None:
        chunks.append(
            Chunk(
                chunk_id=len(chunks),
                page_start=min(p.page for p in group),
                page_end=max(p.page for p in group),
                text=" ".join(p.text for p in group),
            )
        )

    group: list[_Piece] = []
    length = 0
    fresh = 0  # pieces in `group` that were not carried over as overlap
    for piece in pieces:
        add = len(piece.text) + (1 if group else 0)
        if group and length + add > chunk_size:
            emit(group)
            carry: list[_Piece] = []
            carried = 0
            for old in reversed(group):
                if carried + len(old.text) + 1 > chunk_overlap:
                    break
                carry.insert(0, old)
                carried += len(old.text) + 1
            group = carry
            length = sum(len(p.text) for p in group) + max(len(group) - 1, 0)
            fresh = 0
            add = len(piece.text) + (1 if group else 0)
        group.append(piece)
        length += add
        fresh += 1
    if group and fresh:
        tail = " ".join(p.text for p in group)
        if chunks and len(tail) < _MIN_CHUNK_CHARS:
            last = chunks[-1]
            chunks[-1] = last.model_copy(
                update={
                    "text": f"{last.text} {' '.join(p.text for p in group[-fresh:])}",
                    "page_end": max(last.page_end, *(p.page for p in group)),
                }
            )
        else:
            emit(group)
    return chunks
