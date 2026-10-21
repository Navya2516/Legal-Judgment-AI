"""Decide what text the language model gets to see.

Short judgments are sent whole. Long ones (more than `llm_max_context_chars`)
cannot be sent whole, so the model is given passages chosen by retrieval: the
opening and closing passages plus the best matches for fixed questions about
facts, issues, reasoning and the final order. The result says which mode was
used so the reader knows how much of the judgment the summary is based on.
"""
import re
from dataclasses import dataclass
from typing import Callable, Optional

from app.config import Settings
from app.services.embedder import Embedder
from app.services.index_store import IndexStore
from app.services.indexing import is_stale, search_index
from app.utils.errors import ConflictError

ASPECT_QUERIES = [
    "background facts of the case and what happened between the parties",
    "the questions or issues the court has to decide",
    "arguments made by the petitioner and the respondent",
    "the court's reasoning and analysis of the law",
    "the final conclusion, holding and what the court decided",
    "the final order, relief granted, directions and costs",
]
PER_ASPECT = 10
EDGE_CHUNKS = 3


@dataclass
class Context:
    text: str
    pages: set[int]
    mode: str  # full_text | retrieved_passages
    note: Optional[str]


def build_context(
    doc_id: str,
    cleaned: dict[int, str],
    settings: Settings,
    index_store: IndexStore,
    get_embedder: Callable[[], Embedder],
    *,
    aspects: Optional[list[str]] = None,
    per_aspect: int = PER_ASPECT,
    purpose: str = "summary",
    focus: str = "facts, issues, reasoning and the final order",
) -> Context:
    total_chars = sum(len(t) for t in cleaned.values())
    if total_chars <= settings.llm_max_context_chars:
        parts = [f"[Page {n}]\n{text}" for n, text in sorted(cleaned.items()) if text]
        return Context("\n\n".join(parts), {n for n, t in cleaned.items() if t}, "full_text", None)

    if not index_store.exists(doc_id):
        raise ConflictError(
            "This judgment is long, so its summary is built from retrieved passages, but its "
            "search index is not ready. Wait for index_status 'ready' or rebuild it with POST /index.",
            code="index_not_ready",
        )
    loaded = index_store.load(doc_id)
    if is_stale(loaded.meta, settings):
        raise ConflictError(
            "The search index is out of date. Rebuild it with POST /index first.", code="index_stale"
        )
    embedder = get_embedder()
    chosen: dict[int, None] = {}  # chunk ids in priority order
    for cid in list(range(min(EDGE_CHUNKS, len(loaded.chunks)))):
        chosen[cid] = None
    for query in aspects or ASPECT_QUERIES:
        for hit in search_index(loaded, embedder, query, per_aspect):
            chosen.setdefault(hit.chunk.chunk_id, None)
    for cid in range(max(0, len(loaded.chunks) - EDGE_CHUNKS), len(loaded.chunks)):
        chosen.setdefault(cid, None)

    budget = settings.llm_max_context_chars
    kept: list[int] = []
    used = 0
    for cid in chosen:
        size = len(loaded.chunks[cid].text) + 20
        if used + size > budget:
            continue
        kept.append(cid)
        used += size
    kept.sort()

    pages: set[int] = set()
    parts = []
    for cid in kept:
        chunk = loaded.chunks[cid]
        span = chunk.page_start if chunk.page_start == chunk.page_end else f"{chunk.page_start}-{chunk.page_end}"
        label = "Page" if chunk.page_start == chunk.page_end else "Pages"
        parts.append(f"[{label} {span}]\n{chunk.text}")
        pages.update(range(chunk.page_start, chunk.page_end + 1))
    note = (
        f"This judgment is long ({len(cleaned)} pages). The {purpose} is based on {len(kept)} passages "
        f"from {len(pages)} pages chosen for relevance (the opening, the ending and the best matches "
        f"for {focus}), not on every page. Detailed or minority "
        "opinions may be under-represented."
    )
    return Context("\n\n".join(parts), pages, "retrieved_passages", note)


