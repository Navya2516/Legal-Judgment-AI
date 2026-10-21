"""Schemas for translated summaries and provision explanations."""
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.analysis import Grounding, Status

# ok: translated and passed the checks.
# numbers_changed: a number in the English is missing, or a new one appeared.
# wrong_language: the reply is mostly not in the target script.
# untranslated: the model gave nothing usable, so the English text is shown.
Check = Literal["ok", "numbers_changed", "wrong_language", "untranslated"]


# ----- what we ask the model to return -----

class RawTranslationItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    text: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def _id_to_str(cls, value: Any) -> str:
        return str(value).strip()

    @field_validator("text", mode="before")
    @classmethod
    def _text_to_str(cls, value: Any) -> str:
        return "" if value is None else str(value)


class RawTranslations(BaseModel):
    model_config = ConfigDict(extra="ignore")
    translations: list[RawTranslationItem] = Field(default_factory=list)

    @field_validator("translations", mode="before")
    @classmethod
    def _accept_mapping(cls, value: Any) -> Any:
        # Some replies come back as {"id": "text", ...}; accept that too.
        if isinstance(value, dict):
            return [{"id": key, "text": text} for key, text in value.items()]
        return value


# ----- what the API returns -----

class TranslationQuality(BaseModel):
    items_total: int
    ok: int
    flagged: int = Field(description="Translated, but a check failed (numbers or language). Read these with care.")
    untranslated: int = Field(description="No usable translation; the English text is shown instead.")


class TranslatedPoint(BaseModel):
    text: str = Field(description="The translated sentence.")
    source_text: str = Field(description="The English sentence it was translated from.")
    pages: list[int]
    status: Status = Field(description="Evidence status of the English point (verified or cited).")
    quote: Optional[str] = Field(default=None, description="Word-for-word evidence, always in the original English.")
    check: Check


class TranslatedSummary(BaseModel):
    document_id: str
    language: str
    language_name: str
    generated_at: datetime
    model: Optional[str] = Field(default=None, description="Model that translated (null for English).")
    source_generated_at: datetime = Field(description="When the English summary this was made from was generated.")
    stale: bool = Field(default=False, description="True if the English summary was regenerated after this translation.")
    mode: Literal["full_text", "retrieved_passages"]
    pages_in_context: int
    total_pages: int
    coverage_note: Optional[str] = None
    case_title: Optional[str] = Field(default=None, description="Kept as written in the judgment.")
    court: Optional[str] = None
    date: Optional[str] = None
    case_number: Optional[str] = None
    plain_summary: list[TranslatedPoint] = Field(default_factory=list)
    facts: list[TranslatedPoint] = Field(default_factory=list)
    issues: list[TranslatedPoint] = Field(default_factory=list)
    holding: list[TranslatedPoint] = Field(default_factory=list)
    reasoning: list[TranslatedPoint] = Field(default_factory=list)
    final_order: list[TranslatedPoint] = Field(default_factory=list)
    labels: dict[str, str]
    grounding: Grounding
    quality: TranslationQuality
    disclaimer: str
    disclaimer_en: str
    translation_notice: Optional[str] = None
    translation_notice_en: Optional[str] = None


class TranslatedProvision(BaseModel):
    key: str
    role_in_case: str
    source_text: str
    pages: list[int]
    status: Status
    quote: Optional[str] = None
    check: Check


class TranslatedProvisions(BaseModel):
    document_id: str
    language: str
    language_name: str
    generated_at: datetime
    model: Optional[str] = None
    source_generated_at: datetime
    stale: bool = False
    items: list[TranslatedProvision]
    labels: dict[str, str]
    grounding: Grounding
    quality: TranslationQuality
    disclaimer: str
    disclaimer_en: str
    translation_notice: Optional[str] = None
    translation_notice_en: Optional[str] = None
