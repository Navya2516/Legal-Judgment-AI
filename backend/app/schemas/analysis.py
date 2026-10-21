"""Schemas for summaries, provisions and their evidence."""
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

Status = Literal["verified", "cited"]


# ----- what we ask the model to return (validated leniently) -----

def _to_pages(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, (int, str)):
        value = [value]
    pages: list[int] = []
    for item in value if isinstance(value, list) else []:
        try:
            number = int(str(item).strip())
        except ValueError:
            continue
        if number >= 1:
            pages.append(number)
    return pages


class RawPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str = Field(min_length=1)
    pages: list[int] = Field(default_factory=list)
    quote: Optional[str] = None

    @field_validator("pages", mode="before")
    @classmethod
    def _coerce_pages(cls, value: Any) -> list[int]:
        return _to_pages(value)


class RawSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    case_title: Optional[str] = None
    court: Optional[str] = None
    date: Optional[str] = None
    case_number: Optional[str] = None
    plain_summary: list[RawPoint] = Field(default_factory=list)
    facts: list[RawPoint] = Field(default_factory=list)
    issues: list[RawPoint] = Field(default_factory=list)
    holding: list[RawPoint] = Field(default_factory=list)
    reasoning: list[RawPoint] = Field(default_factory=list)
    final_order: list[RawPoint] = Field(default_factory=list)


class RawProvisionNote(BaseModel):
    model_config = ConfigDict(extra="ignore")
    key: str
    role_in_case: str = Field(min_length=1)
    pages: list[int] = Field(default_factory=list)
    quote: Optional[str] = None

    @field_validator("pages", mode="before")
    @classmethod
    def _coerce_pages(cls, value: Any) -> list[int]:
        return _to_pages(value)


class RawProvisionNotes(BaseModel):
    model_config = ConfigDict(extra="ignore")
    provisions: list[RawProvisionNote] = Field(default_factory=list)


# ----- what the API returns -----

class Point(BaseModel):
    text: str
    pages: list[int] = Field(description="Physical PDF pages where the supporting words were found.")
    status: Status = Field(description="verified: the quote was found on the page; cited: valid page but quote not matched.")
    quote: Optional[str] = None


class Grounding(BaseModel):
    points_total: int = Field(description="Claims the model made.")
    verified: int
    cited: int
    dropped_unsupported: int = Field(description="Claims removed because no valid page backed them.")


class SummaryResult(BaseModel):
    document_id: str
    generated_at: datetime
    model: str
    mode: Literal["full_text", "retrieved_passages"]
    pages_in_context: int
    total_pages: int
    coverage_note: Optional[str] = None
    case_title: Optional[str] = None
    court: Optional[str] = None
    date: Optional[str] = None
    case_number: Optional[str] = None
    plain_summary: list[Point] = Field(default_factory=list)
    facts: list[Point] = Field(default_factory=list)
    issues: list[Point] = Field(default_factory=list)
    holding: list[Point] = Field(default_factory=list)
    reasoning: list[Point] = Field(default_factory=list)
    final_order: list[Point] = Field(default_factory=list)
    grounding: Grounding
    disclaimer: str


class FirstMention(BaseModel):
    page: int
    text: str


class Provision(BaseModel):
    key: str
    label: str
    kind: Literal["article", "section", "rule", "order_rule"]
    number: str
    act: Optional[str] = None
    act_basis: Optional[Literal["stated", "assumed"]] = Field(
        default=None,
        description="stated: the judgment names the Act next to it; assumed: a bare 'Article N' taken to mean the Constitution.",
    )
    mentions: int
    page_count: int
    pages: list[int] = Field(description="Up to the first 100 pages where it appears.")
    variants: list[str] = Field(default_factory=list, description="Sub-clauses seen, e.g. 19(1)(a).")
    first_mention: FirstMention


class ProvisionList(BaseModel):
    document_id: str
    total: int
    returned: int
    provisions: list[Provision]
    note: str


class ProvisionExplanation(BaseModel):
    key: str
    role_in_case: str
    pages: list[int]
    status: Status
    quote: Optional[str] = None


class ProvisionExplanations(BaseModel):
    document_id: str
    generated_at: datetime
    model: str
    items: list[ProvisionExplanation]
    grounding: Grounding
    disclaimer: str


class ProvisionExplainRequest(BaseModel):
    top_n: int = Field(default=8, ge=1, le=15, description="Explain the N most-mentioned provisions.")
