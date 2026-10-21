"""Building a short, readable preview of a document's text."""
from app.schemas.documents import PageText


def build_preview(pages: list[PageText], max_chars: int) -> tuple[str, bool]:
    """Join page texts, each marked "[Page N]", up to roughly `max_chars`.

    Returns (preview, truncated). Empty pages are skipped.
    """
    parts: list[str] = []
    used = 0
    truncated = False
    for page in pages:
        if not page.text.strip():
            continue
        remaining = max_chars - used
        if remaining <= 0:
            truncated = True
            break
        block = f"[Page {page.page_number}]\n{page.text}"
        if len(block) > remaining:
            parts.append(block[:remaining].rstrip() + "…")
            truncated = True
            break
        parts.append(block)
        used += len(block) + 2
    return "\n\n".join(parts), truncated
