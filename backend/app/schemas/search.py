"""Schemas for chunks, the search index and retrieval results."""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class IndexStatus(str, Enum):
    none = "none"  # not built yet
    indexing = "indexing"
    ready = "ready"
    failed = "failed"


class Chunk(BaseModel):
    """A passage of the judgment. Page numbers are physical PDF pages."""

    chunk_id: int = Field(ge=0)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    text: str


class ChunkList(BaseModel):
    document_id: str
    chunks: list[Chunk]
    total: int
    offset: int
    limit: int


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000, description="Question or keywords.")
    top_k: Optional[int] = Field(
        default=None, ge=1, le=20, description="How many passages to return."
    )


class SearchHit(BaseModel):
    rank: int
    score: float = Field(description="Cosine similarity, higher is closer (max 1.0).")
    chunk: Chunk


class SearchResponse(BaseModel):
    document_id: str
    query: str
    top_k: int
    embedding_model: str
    hits: list[SearchHit]


class IndexInfo(BaseModel):
    document_id: str
    index_status: IndexStatus
    chunk_count: int = 0
    embedding_model: Optional[str] = None
    embedding_dim: Optional[int] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    stale: bool = False
    error: Optional[str] = None
