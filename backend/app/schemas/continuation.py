"""Schemas for case continuation insights ("what happens next")."""
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.analysis import Grounding, Point, RawPoint, Status, _to_pages
from app.schemas.translation import Check, TranslatedPoint, TranslationQuality

CourtLevel = Literal["supreme_court", "high_court", "trial_court", "tribunal", "unknown"]
Outcome = Literal[
    "allowed", "partly_allowed", "dismissed", "disposed_of", "remanded", "reference_answered", "other"
]
OUTCOMES: tuple[str, ...] = (
    "allowed", "partly_allowed", "dismissed", "disposed_of", "remanded", "reference_answered", "other"
)


# ----- what we ask the model to return (validated leniently) -----

class RawDisposition(BaseModel):
    model_config = ConfigDict(extra="ignore")
    label: str = "other"
    text: str = Field(min_length=1)
    pages: list[int] = Field(default_factory=list)
    quote: Optional[str] = None

    @field_validator("pages", mode="before")
    @classmethod
    def _coerce_pages(cls, value: Any) -> list[int]:
        return _to_pages(value)

    @field_validator("label", mode="before")
    @classmethod
    def _label_to_str(cls, value: Any) -> str:
        return "other" if value is None else str(value).strip().lower().replace(" ", "_").replace("-", "_")


class RawContinuation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    disposition: Optional[RawDisposition] = None
    directions: list[RawPoint] = Field(default_factory=list)
    deadlines: list[RawPoint] = Field(default_factory=list)
    further_proceedings: list[RawPoint] = Field(default_factory=list)

    @field_validator("disposition", mode="before")
    @classmethod
    def _lenient_disposition(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"text": value} if value.strip() else None
        if isinstance(value, dict) and not str(value.get("text") or "").strip():
            return None
        return value


# ----- what the API returns -----

class Disposition(BaseModel):
    label: Outcome
    text: str
    pages: list[int]
    status: Status
    quote: Optional[str] = None


class Avenue(BaseModel):
    id: str
    title: str
    description: str
    basis: Optional[str] = Field(
        default=None, description="The provision or case this route rests on, if there is a well-known one."
    )


class ContinuationResult(BaseModel):
    document_id: str
    generated_at: datetime
    model: str
    mode: Literal["full_text", "retrieved_passages"]
    pages_in_context: int
    total_pages: int
    coverage_note: Optional[str] = None
    court_level: CourtLevel
    court_level_basis: str = Field(description="How the court level was decided, so a reader can check it.")
    # From the judgment (each point is checked against its text).
    disposition: Optional[Disposition] = None
    directions: list[Point] = Field(default_factory=list)
    deadlines: list[Point] = Field(default_factory=list)
    further_proceedings: list[Point] = Field(default_factory=list)
    grounding: Grounding
    # NOT from the judgment: fixed general information chosen by court level.
    avenues: list[Avenue] = Field(default_factory=list)
    avenues_intro: str
    avenues_notice: str
    disclaimer: str


# ----- translations -----

class TranslatedDisposition(BaseModel):
    label: Outcome
    label_name: str = Field(description="The outcome word in the target language.")
    text: str
    source_text: str
    pages: list[int]
    status: Status
    quote: Optional[str] = None
    check: Check


class TranslatedAvenue(BaseModel):
    id: str
    title: str
    description: str
    basis: Optional[str] = None
    source_title: str
    source_description: str
    check: Check


class TranslatedContinuation(BaseModel):
    document_id: str
    language: str
    language_name: str
    generated_at: datetime
    model: Optional[str] = None
    source_generated_at: datetime
    stale: bool = False
    mode: Literal["full_text", "retrieved_passages"]
    pages_in_context: int
    total_pages: int
    coverage_note: Optional[str] = None
    court_level: CourtLevel
    court_level_name: str
    court_level_basis: str
    disposition: Optional[TranslatedDisposition] = None
    directions: list[TranslatedPoint] = Field(default_factory=list)
    deadlines: list[TranslatedPoint] = Field(default_factory=list)
    further_proceedings: list[TranslatedPoint] = Field(default_factory=list)
    avenues: list[TranslatedAvenue] = Field(default_factory=list)
    avenues_intro: str
    avenues_notice: str
    labels: dict[str, str]
    grounding: Grounding
    quality: TranslationQuality
    disclaimer: str
    disclaimer_en: str
    translation_notice: Optional[str] = None
    translation_notice_en: Optional[str] = None
