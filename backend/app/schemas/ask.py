"""Schemas for asking a question about one judgment."""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.analysis import Grounding, RawPoint, Status
from app.schemas.translation import TranslationQuality


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500, description="A question about this judgment.")
    lang: str = Field(default="en", min_length=2, max_length=5, description="Answer language: en, ta, hi, te, ml or kn.")
    top_k: int = Field(default=6, ge=1, le=10, description="How many passages of the judgment to read.")

    @field_validator("question")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 3:
            raise ValueError("The question is too short.")
        return value


class RawAnswer(BaseModel):
    """What we ask the model to return (validated leniently)."""

    model_config = ConfigDict(extra="ignore")
    answerable: bool = True
    points: list[RawPoint] = Field(default_factory=list)

    @field_validator("answerable", mode="before")
    @classmethod
    def _bool(cls, value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() not in ("false", "no", "0")
        return bool(value)


class AnswerPoint(BaseModel):
    text: str
    source_text: str = Field(description="The English sentence (same as text when the answer is in English).")
    pages: list[int]
    status: Status
    quote: Optional[str] = None
    check: str = "ok"


class Passage(BaseModel):
    """A passage that was read to answer the question (always the original English)."""

    pages: list[int]
    score: float
    excerpt: str


class AskResponse(BaseModel):
    document_id: str
    question: str
    language: str
    language_name: str
    generated_at: datetime
    model: str
    answered: bool = Field(description="False when the judgment passages do not answer the question.")
    message: Optional[str] = Field(default=None, description="Why there is no answer, when answered is false.")
    answer: list[AnswerPoint]
    passages: list[Passage]
    grounding: Grounding
    quality: Optional[TranslationQuality] = None
    disclaimer: str
    translation_notice: Optional[str] = None
