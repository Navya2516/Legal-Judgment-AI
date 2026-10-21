"""Schemas for languages and the legal disclaimer."""
from pydantic import BaseModel


class Language(BaseModel):
    code: str
    name: str
    native_name: str


class LanguageList(BaseModel):
    languages: list[Language]
    default: str = "en"


class DisclaimerResponse(BaseModel):
    disclaimer: str
